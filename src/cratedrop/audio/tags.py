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


def read_meta(path: Path) -> TrackMeta:
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

    return TrackMeta(
        source_path=str(path),
        title=title,
        artist=_first(tags, "artist", "albumartist"),
        album=_first(tags, "album"),
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
