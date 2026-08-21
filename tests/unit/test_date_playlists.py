import datetime
import json
import shutil
from pathlib import Path

from cratedrop.export.builder import INGEST_DATES_REL, build_image
from cratedrop.formats.pdb.vendor_api import Database

CLICK = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"


def _drop(staging: Path, name: str, salt: bytes = b"") -> Path:
    dest = staging / name
    shutil.copy2(CLICK, dest)
    if salt:  # distinct content -> distinct sha
        with open(dest, "ab") as fh:
            fh.write(salt)
    return dest


def _playlists(processed: Path) -> dict[str, int]:
    db = Database.from_file(processed / "PIONEER" / "rekordbox" / "export.pdb")
    names = {n.id: n.name for n in db.playlist_tree}
    counts: dict[str, int] = {}
    for entry in db.playlist_entries:
        name = names.get(entry.playlist_id, "?")
        counts[name] = counts.get(name, 0) + 1
    return counts


def _today_name() -> str:
    t = datetime.date.today()
    return f"{t.month:02d}/{t.day:02d}/{t.year}"


def test_no_retroactive_playlists_then_new_tracks_get_today(tmp_path):
    staging, processed = tmp_path / "s", tmp_path / "p"
    staging.mkdir()
    _drop(staging, "existing.wav")
    build_image(staging, processed)  # feature's first run: no date playlists
    counts = _playlists(processed)
    assert counts == {"cratedrop": 1}

    _drop(staging, "new_one.wav", b"\x01")
    _drop(staging, "new_two.wav", b"\x02")
    build_image(staging, processed)
    counts = _playlists(processed)
    assert counts["cratedrop"] == 3
    assert counts[_today_name()] == 2  # both new tracks, not the old one

    # dates are sticky: another rebuild changes nothing
    build_image(staging, processed)
    assert _playlists(processed) == counts
    dates = json.loads((processed / INGEST_DATES_REL).read_text())
    assert list(dates.values()).count("") == 1  # pre-existing track stays unstamped
