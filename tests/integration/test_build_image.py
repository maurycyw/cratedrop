import shutil
from pathlib import Path

import pytest
from pyrekordbox.anlz import AnlzFile

from cratedrop.deploy.usb import SyncPlan, apply_sync, plan_sync
from cratedrop.export.builder import build_image, load_manifest
from cratedrop.formats.pdb.vendor_api import Database

FIXTURE_AUDIO = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"


@pytest.fixture(scope="module")
def image(tmp_path_factory) -> tuple[Path, object]:
    staging = tmp_path_factory.mktemp("staging")
    processed = tmp_path_factory.mktemp("processed")
    shutil.copy2(FIXTURE_AUDIO, staging / "click_120bpm.wav")
    report = build_image(staging, processed)
    return processed, report


def test_image_structure(image):
    processed, report = image
    assert report.tracks == 1
    assert (processed / "PIONEER" / "rekordbox" / "export.pdb").exists()
    assert (processed / "PIONEER" / "rekordbox" / "exportExt.pdb").exists()
    audio = list((processed / "Contents").rglob("*.wav"))
    assert len(audio) == 1


def test_pdb_references_real_files(image):
    processed, _ = image
    db = Database.from_file(processed / "PIONEER" / "rekordbox" / "export.pdb")
    ours = [t for t in db.tracks if t.title == "click_120bpm"]
    assert len(ours) == 1
    track = ours[0]
    assert (processed / track.file_path.lstrip("/")).exists()
    assert track.analyze_path.endswith("ANLZ0000.DAT")
    dat_path = processed / track.analyze_path.lstrip("/")
    assert dat_path.exists()
    # ANLZ PPTH must point back at the audio path
    parsed = AnlzFile.parse_file(dat_path)
    assert parsed.get_tag("PPTH").get() == track.file_path


def test_manifest_covers_generated_files(image):
    processed, _ = image
    manifest = load_manifest(processed)
    assert manifest is not None
    assert any(k.endswith("ANLZ0000.DAT") for k in manifest)
    assert "PIONEER/rekordbox/export.pdb" in manifest


def test_rebuild_uses_cache(image):
    processed, _ = image
    staging_dir = processed.parent / "staging2"
    staging_dir.mkdir(exist_ok=True)
    shutil.copy2(FIXTURE_AUDIO, staging_dir / "click_120bpm.wav")
    report = build_image(staging_dir, processed)
    assert report.cached == ["click_120bpm.wav"]
    assert report.analyzed == []


def test_flash_plan_and_apply(image, tmp_path):
    processed, _ = image
    mount = tmp_path / "fake_stick"
    mount.mkdir()
    plan = plan_sync(processed, mount)
    assert plan.copy and not plan.deck_modified
    apply_sync(processed, mount, plan)
    # second sync: everything unchanged
    plan2 = plan_sync(processed, mount)
    assert plan2.copy == [] and plan2.unchanged > 0

    # simulate the deck rewriting the pdb
    pdb_on_stick = mount / "PIONEER" / "rekordbox" / "export.pdb"
    pdb_on_stick.write_bytes(pdb_on_stick.read_bytes() + b"\x00")
    plan3 = plan_sync(processed, mount)
    assert "PIONEER/rekordbox/export.pdb" in plan3.deck_modified


def test_flash_removes_stale_wal_siblings(image, tmp_path):
    processed, _ = image
    mount = tmp_path / "stick_with_stale_wal"
    (mount / "PIONEER" / "rekordbox").mkdir(parents=True)
    stale_wal = mount / "PIONEER" / "rekordbox" / "exportLibrary.db-wal"
    stale_shm = mount / "PIONEER" / "rekordbox" / "exportLibrary.db-shm"
    stale_wal.write_bytes(b"stale")
    stale_shm.write_bytes(b"stale")
    plan = plan_sync(processed, mount)
    apply_sync(processed, mount, plan)
    assert (mount / "PIONEER" / "rekordbox" / "exportLibrary.db").exists()
    assert not stale_wal.exists() and not stale_shm.exists()
