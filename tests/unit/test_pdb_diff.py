from pathlib import Path

import pytest
from rich.console import Console

from cratedrop.formats.pdb.vendor_api import Database, PdbEditor
from cratedrop.verify.diff import diff_pdb

FIXTURES = Path(__file__).parent.parent / "fixtures" / "thirdparty"
ONE_SONG = FIXTURES / "one-song-export.pdb"


@pytest.fixture()
def console() -> Console:
    return Console(file=open("/dev/null", "w"), force_terminal=False)


def test_read_one_song_export():
    db = Database.from_file(ONE_SONG)
    assert len(db.tracks) == 1
    track = db.tracks[0]
    assert track.title == "Super Smash Bros."
    assert track.tempo == 14600
    assert track.file_path.startswith("/Contents/")


def test_self_diff_is_clean(console):
    assert diff_pdb(console, ONE_SONG, ONE_SONG) is False


def test_diff_detects_field_change(tmp_path, console):
    ed = PdbEditor.from_file(ONE_SONG)
    ed.set_track_field(track_id=1, field="rating", value=5)
    mutated = tmp_path / "mutated.pdb"
    ed.save(mutated)
    assert diff_pdb(console, mutated, ONE_SONG) is True


def test_diff_detects_added_track(tmp_path, console):
    ed = PdbEditor.from_file(ONE_SONG)
    ed.add_track(title="New Track", file_path="/Contents/A/B/new.mp3",
                 artist="A", album="B", genre="House", key="Am",
                 tempo=12800, duration=200, bitrate=320, sample_rate=44100)
    mutated = tmp_path / "with-track.pdb"
    ed.save(mutated)
    # sanity: independent parse of the mutated file sees both tracks
    db = Database.from_file(mutated)
    assert {t.title for t in db.tracks} == {"Super Smash Bros.", "New Track"}
    assert diff_pdb(console, mutated, ONE_SONG) is True
