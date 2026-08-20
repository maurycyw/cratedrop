import os
import shutil
import time
from pathlib import Path

from cratedrop.export.builder import scan_staging

CLICK = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"


def test_scan_staging_newest_first(tmp_path):
    now = time.time()
    for name, age_days in (("old.wav", 300), ("newest.wav", 1), ("mid.wav", 30)):
        dest = tmp_path / name
        shutil.copy2(CLICK, dest)
        os.utime(dest, (now - age_days * 86400, now - age_days * 86400))
    names = [p.name for p in scan_staging(tmp_path)]
    assert names == ["newest.wav", "mid.wav", "old.wav"]


def test_flash_copy_order_audio_first_pdb_last(tmp_path):
    from cratedrop.deploy.usb import plan_sync
    import json

    processed = tmp_path / "processed"
    now = time.time()
    files = {
        "PIONEER/rekordbox/export.pdb": 0,
        "Contents/A/old.wav": 300,
        "Contents/A/new.wav": 1,
        "PIONEER/USBANLZ/P000/00000001/ANLZ0000.DAT": 0,
    }
    manifest = {}
    for rel, age_days in files.items():
        p = processed / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 4)
        os.utime(p, (now - age_days * 86400,) * 2)
        manifest[rel] = {"size": 4, "sha1": "3c363836cf4e16666669a25da280a1865c2d2874"}
    (processed / "PIONEER" / ".cratedrop.json").write_text(json.dumps(manifest))

    mount = tmp_path / "stick"
    mount.mkdir()
    plan = plan_sync(processed, mount)
    assert plan.copy[0] == "Contents/A/new.wav"
    assert plan.copy[1] == "Contents/A/old.wav"
    assert plan.copy[-1] == "PIONEER/rekordbox/export.pdb"
