import json
import shutil
from pathlib import Path

import pytest

from cratedrop.cache import load_any
from cratedrop.deploy.harvest import harvest
from cratedrop.deploy.usb import apply_sync, plan_sync
from cratedrop.export.builder import build_image, load_manifest
from cratedrop.formats.anlz import writer
from cratedrop.model import CueKind, CuePoint, CueSource

FIXTURE_AUDIO = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"
GOLDEN_LOCAL = Path(__file__).parent.parent / "fixtures" / "golden-local" / "old-pc-library"


def test_deck_cue_round_trip(tmp_path):
    staging = tmp_path / "staging"
    processed = tmp_path / "processed"
    mount = tmp_path / "stick"
    staging.mkdir(), mount.mkdir()
    shutil.copy2(FIXTURE_AUDIO, staging / "click_120bpm.wav")

    build_image(staging, processed)
    apply_sync(processed, mount, plan_sync(processed, mount))

    # find the track's analysis + its ANLZ location on the "stick"
    manifest = load_manifest(processed)
    audio_rel = next(k for k in manifest if k.startswith("Contents/"))
    sha = manifest[audio_rel]["sha1"]
    analysis = load_any(processed, sha)
    ext_rel = next(k for k in manifest if k.endswith("ANLZ0000.EXT"))

    # simulate the deck: rewrite the stick's EXT with an extra hot cue H
    deck_cue = CuePoint(kind=CueKind.HOT, slot="H", time_ms=30_000.0,
                        label="DECKCUE", source=CueSource.DECK)
    modified = analysis.replace_cues(analysis.cues + (deck_cue,))
    (mount / ext_rel).write_bytes(writer.build_ext(modified, "/" + audio_rel))

    report = harvest(mount, processed)
    assert report.cues_found >= 1
    assert report.tracks_updated == ["click_120bpm"]

    after = load_any(processed, sha)
    deck_cues = [c for c in after.cues if c.source == CueSource.DECK]
    assert any(c.slot == "H" and c.time_ms == 30_000.0 for c in deck_cues)
    # heuristic cues survived alongside
    assert any(c.source == CueSource.HEURISTIC for c in after.cues)

    # unmodified files are untouched: re-harvest is a no-op
    report2 = harvest(mount, processed)
    assert report2.tracks_updated == []


@pytest.mark.skipif(not GOLDEN_LOCAL.exists(), reason="local golden not present")
def test_history_harvest_from_real_library(tmp_path):
    report = harvest(GOLDEN_LOCAL, tmp_path / "processed")
    assert report.history_playlists == 36
    sessions = json.loads(
        (tmp_path / "processed" / ".cratedrop" / "history" / "harvested.json").read_text())
    assert len(sessions) == 36
    assert all(isinstance(v, list) for v in sessions.values())


def test_onelibrary_history_harvest(tmp_path):
    """Simulate an XDJ-AZ writing a play-history session into our OneLibrary."""
    from cratedrop.formats.onelibrary import connect

    staging, processed, mount = tmp_path / "s", tmp_path / "p", tmp_path / "stick"
    staging.mkdir(), mount.mkdir()
    shutil.copy2(FIXTURE_AUDIO, staging / "click_120bpm.wav")
    build_image(staging, processed)
    apply_sync(processed, mount, plan_sync(processed, mount))

    db = mount / "PIONEER" / "rekordbox" / "exportLibrary.db"
    con = connect(db)
    con.execute("INSERT INTO history (history_id, sequenceNo, name, attribute, history_id_parent) "
                "VALUES (1, 1, 'HISTORY 001', 0, 0)")
    con.execute("INSERT INTO history_content (history_id, content_id, sequenceNo) VALUES (1, 1, 1)")
    con.commit(); con.close()

    report = harvest(mount, processed)
    assert report.history_playlists == 1
    sessions = json.loads((processed / ".cratedrop" / "history" / "harvested.json").read_text())
    assert list(sessions) == ["onelib:HISTORY 001"]
    assert sessions["onelib:HISTORY 001"][0].endswith("click_120bpm.wav")
