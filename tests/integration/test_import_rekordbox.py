import shutil
from pathlib import Path

from pyrekordbox.rbxml import RekordboxXml

from cratedrop.cache import load_any
from cratedrop.audio.tags import sha1_file
from cratedrop.export.builder import build_image
from cratedrop.import_rekordbox import import_xml
from cratedrop.model import CueKind, CueSource

CLICK = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"


def _setup(tmp_path):
    staging, processed = tmp_path / "s", tmp_path / "p"
    staging.mkdir()
    for name, salt in (("one.wav", b"\x01"), ("two.wav", b"\x02")):
        dest = staging / name
        shutil.copy2(CLICK, dest)
        with open(dest, "ab") as fh:
            fh.write(salt)

    xml = RekordboxXml()
    # location matches by FILENAME only (exported on another machine)
    t1 = xml.add_track(location="/Users/dj/Music/one.wav", Name="One", AverageBpm=120.0)
    t1.add_mark(Name="DROP", Type="cue", Start=30.0, Num=1)        # hot B
    t1.add_mark(Name="", Type="loop", Start=60.0, End=63.75, Num=2)  # hot C loop
    t1.add_mark(Name="", Type="cue", Start=5.0, Num=-1)            # memory
    t1.add_tempo(Inizio=0.499, Bpm=120.0, Metro="4/4", Battito=1)
    xml.add_track(location="/elsewhere/missing.wav", Name="Gone")
    t3 = xml.add_track(location=str(staging / "two.wav"), Name="Two")
    pl = xml.add_playlist("Peak Time")
    pl.add_track(t1["TrackID"])
    pl.add_track(t3["TrackID"])
    xml_path = tmp_path / "rekordbox.xml"
    xml.save(xml_path)
    return staging, processed, xml_path


def test_import_cues_loops_playlists(tmp_path):
    staging, processed, xml_path = _setup(tmp_path)
    report = import_xml(xml_path, staging, processed)
    assert report.matched == 2
    assert report.unmatched == ["missing.wav"]
    assert report.cues == 3 and report.loops == 1
    assert report.playlists == ["Peak Time"]

    sha = sha1_file(staging / "one.wav")
    stub = load_any(processed, sha)
    cues = {(c.kind, c.slot): c for c in stub.cues}
    assert cues[(CueKind.HOT, "B")].label == "DROP"
    assert cues[(CueKind.HOT, "C")].loop_out_ms == 63_750.0
    assert (CueKind.MEMORY, "") in cues
    assert all(c.source == CueSource.MANUAL for c in stub.cues)

    m3u = staging / "rekordbox playlists" / "Peak Time.m3u8"
    assert m3u.exists() and "one.wav" in m3u.read_text()


def test_imported_cues_survive_analysis_and_reach_the_stick(tmp_path):
    staging, processed, xml_path = _setup(tmp_path)
    import_xml(xml_path, staging, processed, with_grids=True)
    build_image(staging, processed)  # full analysis runs AFTER the import

    sha = sha1_file(staging / "one.wav")
    analysis = load_any(processed, sha)
    manual = [c for c in analysis.cues if c.source == CueSource.MANUAL]
    assert {(c.kind, c.slot) for c in manual} >= {(CueKind.HOT, "B"), (CueKind.HOT, "C")}
    assert analysis.grid.bpm == 120.0          # --with-grids override applied
    assert analysis.grid.first_beat_ms == 499.0

    # and the playlist made it into the device database
    from cratedrop.formats.pdb.vendor_api import Database
    db = Database.from_file(processed / "PIONEER" / "rekordbox" / "export.pdb")
    names = {n.name for n in db.playlist_tree}
    assert "Peak Time" in names
