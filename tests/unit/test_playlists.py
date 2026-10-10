import shutil
from pathlib import Path

import pytest

from cratedrop.export.builder import build_image
from cratedrop.formats.onelibrary import connect
from cratedrop.formats.pdb.vendor_api import Database

CLICK = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"


def _drop(staging: Path, rel: str, salt: bytes = b"") -> Path:
    dest = staging / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CLICK, dest)
    if salt:
        with open(dest, "ab") as fh:
            fh.write(salt)
    return dest


def _pdb_playlists(processed: Path) -> dict[str, int]:
    db = Database.from_file(processed / "PIONEER" / "rekordbox" / "export.pdb")
    names = {n.id: n.name for n in db.playlist_tree}
    out: dict[str, int] = {}
    for e in db.playlist_entries:
        out[names[e.playlist_id]] = out.get(names[e.playlist_id], 0) + 1
    return out


@pytest.fixture()
def cfg_env(tmp_path, monkeypatch):
    import cratedrop.config as cfg
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setattr(cfg, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(cfg, "CONFIG_PATH", cfg_dir / "config.toml")
    return cfg


def test_m3u_playlist_by_filename_and_relative_path(tmp_path, cfg_env):
    staging, processed = tmp_path / "s", tmp_path / "p"
    _drop(staging, "Techno/one.wav", b"\x01")
    _drop(staging, "Techno/two.wav", b"\x02")
    _drop(staging, "House/three.wav", b"\x03")
    # filename entry + relative-path entry + a foreign absolute path + junk
    (staging / "warmup set.m3u8").write_text(
        "#EXTM3U\n"
        "two.wav\n"
        "House/three.wav\n"
        "C:/Users/foreign/one.wav\n"
        "missing.wav\n")
    build_image(staging, processed)
    counts = _pdb_playlists(processed)
    assert counts["warmup set"] == 3  # all three resolve (one via basename)
    con = connect(processed / "PIONEER" / "rekordbox" / "exportLibrary.db")
    n = con.execute("SELECT COUNT(*) FROM playlist_content pc JOIN playlist p "
                    "ON p.playlist_id = pc.playlist_id WHERE p.name = 'warmup set'").fetchone()[0]
    con.close()
    assert n == 3


def test_folder_playlists_opt_in(tmp_path, cfg_env):
    staging, processed = tmp_path / "s", tmp_path / "p"
    _drop(staging, "Techno/one.wav", b"\x01")
    _drop(staging, "House/two.wav", b"\x02")
    _drop(staging, "loose.wav", b"\x03")

    build_image(staging, processed)
    assert "Techno" not in _pdb_playlists(processed)  # off by default

    c = cfg_env.Config.load()
    c.playlists_from_folders = True
    c.save()
    build_image(staging, processed)
    counts = _pdb_playlists(processed)
    assert counts["Techno"] == 1 and counts["House"] == 1  # loose.wav in neither


def test_date_playlists_can_be_disabled(tmp_path, cfg_env):
    staging, processed = tmp_path / "s", tmp_path / "p"
    _drop(staging, "a.wav", b"\x01")
    build_image(staging, processed)        # first run: baseline, no date lists
    _drop(staging, "b.wav", b"\x02")
    c = cfg_env.Config.load()
    c.playlists_by_date = False
    c.save()
    build_image(staging, processed)
    assert list(_pdb_playlists(processed)) == ["cratedrop"]
