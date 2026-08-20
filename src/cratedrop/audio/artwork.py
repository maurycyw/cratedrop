"""Embedded album art extraction and Pioneer-format resizing.

Rekordbox convention (verified from a real export): each artwork id gets
/PIONEER/Artwork/<bucket>/a<id>.jpg at 80x80 plus a<id>_m.jpg at 240x240,
referenced from the pdb artwork table by the a<id>.jpg path.
"""

from __future__ import annotations

import io
from pathlib import Path

import mutagen
from mutagen.flac import FLAC

SMALL = 80
MEDIUM = 240


def extract_embedded_art(path: Path) -> bytes | None:
    """Raw embedded image bytes from a file's tags (APIC / FLAC picture)."""
    try:
        f = mutagen.File(path)
    except Exception:  # noqa: BLE001
        return None
    if f is None:
        return None
    if isinstance(f, FLAC) and f.pictures:
        return bytes(f.pictures[0].data)
    tags = getattr(f, "tags", None)
    if tags is not None and hasattr(tags, "getall"):
        apics = tags.getall("APIC")
        if apics:
            return bytes(apics[0].data)
    return None


def render_pioneer_jpegs(image_bytes: bytes) -> tuple[bytes, bytes] | None:
    """(80x80 jpeg, 240x240 jpeg) center-cropped square, or None if the
    embedded data isn't a decodable image."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception:  # noqa: BLE001
        return None
    img = img.convert("RGB")
    side = min(img.size)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side))

    def jpeg(size: int) -> bytes:
        buf = io.BytesIO()
        img.resize((size, size), Image.LANCZOS).save(buf, "JPEG", quality=90)
        return buf.getvalue()

    return jpeg(SMALL), jpeg(MEDIUM)
