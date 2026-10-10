import shutil
from pathlib import Path

from cratedrop.export.builder import build_image
from cratedrop.formats.onelibrary import connect

CLICK = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"


def test_image_writes_onelibrary(tmp_path):
    staging, processed = tmp_path / "s", tmp_path / "p"
    staging.mkdir()
    (staging / "Some Artist" / "Some Album").mkdir(parents=True)
    shutil.copy2(CLICK, staging / "Some Artist" / "Some Album" / "track.wav")
    build_image(staging, processed)

    db = processed / "PIONEER" / "rekordbox" / "exportLibrary.db"
    assert db.exists()
    con = connect(db)
    rows = con.execute(
        "SELECT c.title, c.bpmx100, c.path, c.analysisDataFilePath, c.fileType, "
        "a.name, al.name, k.name FROM content c "
        "LEFT JOIN artist a ON a.artist_id = c.artist_id_artist "
        "LEFT JOIN album al ON al.album_id = c.album_id "
        "LEFT JOIN key k ON k.key_id = c.key_id").fetchall()
    assert len(rows) == 1
    title, bpm, path, anlz, ftype, artist, album, key = rows[0]
    assert title == "track" and ftype == 11
    assert artist == "Some Artist" and album == "Some Album"
    assert bpm in (12000, 12800)  # detected (dsp extra) or tag-fallback (core-only CI)
    assert path.startswith("/Contents/") and (processed / path.lstrip("/")).exists()
    assert (processed / anlz.lstrip("/")).exists()
    # key row is linked only when key detection (dsp extra) is available
    assert con.execute("SELECT numberOfContents FROM property").fetchone()[0] == 1
    playlists = con.execute("SELECT name FROM playlist ORDER BY sequenceNo").fetchall()
    assert playlists[0] == ("cratedrop",)
    assert con.execute("SELECT COUNT(*) FROM playlist_content").fetchone()[0] >= 1
    con.close()
    # the template's lookup/menu tables must be intact
    con = connect(db)
    assert con.execute("SELECT COUNT(*) FROM menuItem").fetchone()[0] == 27
    con.close()


def test_image_ships_imported_deck_settings(tmp_path, monkeypatch):
    import cratedrop.config as cfg
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / "cfg")
    (tmp_path / "cfg" / "mysettings").mkdir(parents=True)
    (tmp_path / "cfg" / "mysettings" / "DEVSETTING.DAT").write_bytes(b"DEVS")

    staging, processed = tmp_path / "s", tmp_path / "p"
    staging.mkdir()
    shutil.copy2(CLICK, staging / "track.wav")
    build_image(staging, processed)
    assert (processed / "PIONEER" / "DEVSETTING.DAT").read_bytes() == b"DEVS"
    from cratedrop.export.builder import load_manifest
    assert "PIONEER/DEVSETTING.DAT" in load_manifest(processed)
