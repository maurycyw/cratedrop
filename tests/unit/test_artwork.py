import io
import shutil
from pathlib import Path

from mutagen.id3 import APIC
from mutagen.wave import WAVE
from PIL import Image

from cratedrop.audio.artwork import extract_embedded_art, render_pioneer_jpegs

CLICK = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"


def _png_bytes(w: int = 300, h: int = 200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _wav_with_art(tmp_path: Path) -> Path:
    dest = tmp_path / "with_art.wav"
    shutil.copy2(CLICK, dest)
    audio = WAVE(dest)
    audio.add_tags()
    audio.tags.add(APIC(encoding=3, mime="image/png", type=3,
                        desc="Cover", data=_png_bytes()))
    audio.save()
    return dest


def test_extract_and_render(tmp_path):
    src = _wav_with_art(tmp_path)
    raw = extract_embedded_art(src)
    assert raw is not None
    small, medium = render_pioneer_jpegs(raw)
    assert Image.open(io.BytesIO(small)).size == (80, 80)
    assert Image.open(io.BytesIO(medium)).size == (240, 240)


def test_no_art_returns_none(tmp_path):
    dest = tmp_path / "plain.wav"
    shutil.copy2(CLICK, dest)
    assert extract_embedded_art(dest) is None


def test_image_build_writes_artwork(tmp_path):
    from cratedrop.export.builder import build_image
    from cratedrop.formats.pdb.vendor_api import Database

    staging = tmp_path / "staging"
    processed = tmp_path / "processed"
    staging.mkdir()
    _wav_with_art(staging)
    build_image(staging, processed)

    art = processed / "PIONEER" / "Artwork" / "00001" / "a1.jpg"
    assert art.exists()
    assert (processed / "PIONEER" / "Artwork" / "00001" / "a1_m.jpg").exists()
    assert Image.open(art).size == (80, 80)

    db = Database.from_file(processed / "PIONEER" / "rekordbox" / "export.pdb")
    assert len(db.artwork) == 1
    assert db.artwork[0].path == "/PIONEER/Artwork/00001/a1.jpg"
    track = next(t for t in db.tracks if t.title == "with_art")
    assert track.artwork_id == db.artwork[0].id
