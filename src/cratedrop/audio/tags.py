"""Metadata extraction via mutagen → TrackMeta."""

from __future__ import annotations

import hashlib
from pathlib import Path

import mutagen

from ..model import TrackMeta


def _first(tags, *keys: str) -> str:
    if not tags:
        return ""
    for key in keys:
        val = tags.get(key)
        if val:
            return str(val[0] if isinstance(val, list) else val)
    return ""


def _int(text: str) -> int:
    digits = "".join(ch for ch in text.split("/")[0].split("-")[0] if ch.isdigit())
    return int(digits) if digits else 0


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


_NON_NAMES = {"unknownalbum", "unknown album", "unknownartist", "unknown artist",
               "various", "various artists", "music", "tracks", "audio"}


def _folder_fallbacks(path: Path, base_dir: Path | None) -> tuple[str, str]:
    """(artist, album) derived from <base>/<Artist>/<Album>/file layout."""
    if base_dir is None:
        return "", ""
    try:
        parts = path.resolve().relative_to(base_dir.resolve()).parts
    except ValueError:
        return "", ""

    def clean(name: str) -> str:
        return "" if name.lower().strip() in _NON_NAMES else name.strip()

    artist = clean(parts[0]) if len(parts) >= 2 else ""
    album = clean(parts[1]) if len(parts) >= 3 else ""
    return artist, album


def read_meta(path: Path, base_dir: Path | None = None) -> TrackMeta:
    """Metadata with a fallback chain: file tags -> staging folder structure
    (<base>/<Artist>/<Album>/...) -> 'Artist - Title' filename split. Most
    DJ libraries are folder-organized WAVs with no tags at all."""
    audio = mutagen.File(path, easy=True)
    tags = audio.tags if audio else None
    info = audio.info if audio else None

    title = _first(tags, "title") or path.stem
    duration_s = getattr(info, "length", 0.0) or 0.0
    bitrate = getattr(info, "bitrate", 0) or 0
    sample_rate = getattr(info, "sample_rate", 0) or 44100
    if duration_s <= 0:
        # mutagen reports 0 for some WAVs; libsndfile knows better
        try:
            import soundfile as sf
            sfinfo = sf.info(str(path))
            duration_s = sfinfo.frames / sfinfo.samplerate
            sample_rate = sfinfo.samplerate
        except Exception:  # noqa: BLE001 - keep 0, analysis falls back to PCM length
            pass

    artist = _first(tags, "artist", "albumartist")
    album = _first(tags, "album")
    if not artist or not album:
        folder_artist, folder_album = _folder_fallbacks(path, base_dir)
        artist = artist or folder_artist
        album = album or folder_album
    if not artist and " - " in title:
        # untagged, unfoldered "Artist - Title.wav" convention
        left, _, right = title.partition(" - ")
        if left.strip() and right.strip():
            artist, title = left.strip(), right.strip()

    return TrackMeta(
        source_path=str(path),
        title=title,
        artist=artist,
        album=album,
        genre=_first(tags, "genre"),
        year=_int(_first(tags, "date", "year")),
        track_no=_int(_first(tags, "tracknumber")),
        duration_ms=duration_s * 1000.0,
        sample_rate=int(sample_rate),
        bitrate=int(bitrate // 1000) if bitrate > 10_000 else int(bitrate),
        file_size=path.stat().st_size,
        sha1=sha1_file(path),
    )


def tag_bpm(path: Path) -> float | None:
    """BPM from file tags if present (placeholder grid source until real DSP)."""
    audio = mutagen.File(path, easy=True)
    text = _first(audio.tags if audio else None, "bpm")
    try:
        bpm = float(text)
        return bpm if 40.0 <= bpm <= 220.0 else None
    except (TypeError, ValueError):
        return None
