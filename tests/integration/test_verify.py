import shutil
from pathlib import Path

from cratedrop.export.builder import build_image
from cratedrop.verify.integrity import verify_tree

CLICK = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"


def _image(tmp_path: Path) -> Path:
    staging, processed = tmp_path / "s", tmp_path / "p"
    staging.mkdir()
    shutil.copy2(CLICK, staging / "track.wav")
    build_image(staging, processed)
    return processed


def test_healthy_image_verifies(tmp_path):
    assert verify_tree(_image(tmp_path), deep=True) == []


def test_detects_missing_audio(tmp_path):
    processed = _image(tmp_path)
    next((processed / "Contents").rglob("*.wav")).unlink()
    problems = verify_tree(processed)
    assert any("missing" in p for p in problems)


def test_detects_truncated_anlz(tmp_path):
    processed = _image(tmp_path)
    dat = next((processed / "PIONEER" / "USBANLZ").rglob("ANLZ0000.DAT"))
    dat.write_bytes(dat.read_bytes()[:100])
    problems = verify_tree(processed)
    assert any("ANLZ" in p or "mismatch" in p for p in problems)


def test_detects_corrupted_onelibrary(tmp_path):
    processed = _image(tmp_path)
    db = processed / "PIONEER" / "rekordbox" / "exportLibrary.db"
    db.write_bytes(b"\x00" * 1024)
    problems = verify_tree(processed)
    assert any("exportLibrary" in p or "mismatch" in p for p in problems)
