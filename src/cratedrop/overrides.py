"""Per-track manual analysis overrides, keyed by content sha1.

Stored as a sidecar (processed/.cratedrop/overrides/<sha1>.json), separate
from the analysis cache, so they survive re-analysis and analyzer upgrades:
the pipeline re-applies them after every fresh DSP pass.
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import BeatGrid, KeyResult, TrackAnalysis


def _dir(processed_dir: Path) -> Path:
    return processed_dir / ".cratedrop" / "overrides"


def load(processed_dir: Path, sha1: str) -> dict:
    path = _dir(processed_dir) / f"{sha1}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}


def store(processed_dir: Path, sha1: str, **values) -> dict:
    current = load(processed_dir, sha1)
    current.update({k: v for k, v in values.items() if v is not None})
    path = _dir(processed_dir) / f"{sha1}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=1))
    return current


def apply(analysis: TrackAnalysis, ov: dict) -> TrackAnalysis:
    from dataclasses import replace

    if not ov:
        return analysis
    grid = analysis.grid
    if "bpm" in ov or "first_beat_ms" in ov:
        bpm = float(ov.get("bpm") or (grid.bpm if grid else 128.0))
        first = float(ov.get("first_beat_ms",
                             grid.first_beat_ms if grid else 0.0))
        grid = BeatGrid.constant(bpm=bpm, first_beat_ms=first,
                                 duration_ms=analysis.meta.duration_ms,
                                 confidence=1.0)
    key = analysis.key
    if ov.get("key"):
        key = KeyResult(camelot=str(ov["key"]).upper(), standard="",
                        confidence=1.0, source="manual")
    return replace(analysis, grid=grid, key=key)
