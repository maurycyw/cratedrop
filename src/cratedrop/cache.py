"""Analysis cache: one JSON per track, keyed by content sha1 + analyzer versions."""

from __future__ import annotations

from pathlib import Path

from .model import TrackAnalysis

ANALYZER_VERSIONS = {
    # bump a component to invalidate cached results produced by it
    "meta": "1",
    "waveform": "2-butterworth-p95",
    "grid": "placeholder-1",  # tag-BPM/constant grid until real DSP (M4)
}


def cache_dir(processed_dir: Path) -> Path:
    return processed_dir / ".cratedrop" / "cache"


def load(processed_dir: Path, sha1: str) -> TrackAnalysis | None:
    path = cache_dir(processed_dir) / f"{sha1}.json"
    if not path.exists():
        return None
    try:
        analysis = TrackAnalysis.load(path)
    except Exception:  # noqa: BLE001 - corrupt cache entry is just a miss
        return None
    if analysis.analyzer_versions != ANALYZER_VERSIONS:
        return None
    return analysis


def store(processed_dir: Path, analysis: TrackAnalysis) -> None:
    path = cache_dir(processed_dir) / f"{analysis.meta.sha1}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    analysis.save(path)
