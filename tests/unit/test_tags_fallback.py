import shutil
from pathlib import Path

from cratedrop.audio.tags import read_meta

CLICK = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"


def _untagged_wav_at(tmp_path: Path, rel: str) -> Path:
    dest = tmp_path / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CLICK, dest)
    return dest


def test_folder_structure_fallback(tmp_path):
    p = _untagged_wav_at(tmp_path, "Sara Landry/Spiritual Driveby/track one.wav")
    meta = read_meta(p, base_dir=tmp_path)
    assert meta.artist == "Sara Landry"
    assert meta.album == "Spiritual Driveby"
    assert meta.title == "track one"


def test_unknownalbum_folder_treated_as_missing(tmp_path):
    p = _untagged_wav_at(tmp_path, "Maddix/UnknownAlbum/open-sesame.wav")
    meta = read_meta(p, base_dir=tmp_path)
    assert meta.artist == "Maddix"
    assert meta.album == ""


def test_filename_split_when_no_folders(tmp_path):
    p = _untagged_wav_at(tmp_path, "Lilly Allen - Not Fair (DNNS EDIT).wav")
    meta = read_meta(p, base_dir=tmp_path)
    assert meta.artist == "Lilly Allen"
    assert meta.title == "Not Fair (DNNS EDIT)"


def test_folder_artist_beats_filename_split(tmp_path):
    p = _untagged_wav_at(tmp_path, "KUKO/UnknownAlbum/KUKO - Toxic.wav")
    meta = read_meta(p, base_dir=tmp_path)
    assert meta.artist == "KUKO"
    assert meta.title == "KUKO - Toxic"  # title split only applies untagged+unfoldered


def test_no_base_dir_no_crash(tmp_path):
    p = _untagged_wav_at(tmp_path, "plain.wav")
    meta = read_meta(p)
    assert meta.title == "plain"
    assert meta.artist == ""
