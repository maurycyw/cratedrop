"""Musical key detection: essentia (EDM-tuned 'edma' profile) → Camelot.

Fallback: keyfinder-cli (Mixxx's libkeyfinder) via subprocess, if installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

from ..model import KeyResult

# musical key -> Camelot. Minor ring = A, major ring = B.
_CAMELOT = {
    ("Ab", "minor"): "1A", ("G#", "minor"): "1A", ("B", "major"): "1B",
    ("Eb", "minor"): "2A", ("D#", "minor"): "2A", ("F#", "major"): "2B", ("Gb", "major"): "2B",
    ("Bb", "minor"): "3A", ("A#", "minor"): "3A", ("Db", "major"): "3B", ("C#", "major"): "3B",
    ("F", "minor"): "4A", ("Ab", "major"): "4B", ("G#", "major"): "4B",
    ("C", "minor"): "5A", ("Eb", "major"): "5B", ("D#", "major"): "5B",
    ("G", "minor"): "6A", ("Bb", "major"): "6B", ("A#", "major"): "6B",
    ("D", "minor"): "7A", ("F", "major"): "7B",
    ("A", "minor"): "8A", ("C", "major"): "8B",
    ("E", "minor"): "9A", ("G", "major"): "9B",
    ("B", "minor"): "10A", ("D", "major"): "10B",
    ("F#", "minor"): "11A", ("Gb", "minor"): "11A", ("A", "major"): "11B",
    ("Db", "minor"): "12A", ("C#", "minor"): "12A", ("E", "major"): "12B",
}


def to_camelot(key: str, scale: str) -> str:
    return _CAMELOT.get((key, scale.lower()), "")


def detect_key(samples: np.ndarray, sample_rate: int,
               source_path: Path | None = None) -> KeyResult | None:
    try:
        return _essentia_key(samples, sample_rate)
    except Exception:  # noqa: BLE001 - fall through to keyfinder
        if source_path is not None:
            return _keyfinder_key(source_path)
        return None


def _essentia_key(samples: np.ndarray, sample_rate: int) -> KeyResult:
    import essentia.standard as es

    key, scale, strength = es.KeyExtractor(
        profileType="edma", sampleRate=sample_rate)(samples.astype(np.float32))
    camelot = to_camelot(key, scale)
    standard = f"{key} {scale}"
    return KeyResult(camelot=camelot or standard, standard=standard,
                     confidence=float(strength), source="essentia-edma")


def _keyfinder_key(source_path: Path) -> KeyResult | None:
    if not shutil.which("keyfinder-cli"):
        return None
    out = subprocess.run(["keyfinder-cli", "-n", "camelot", str(source_path)],
                         capture_output=True, text=True, timeout=120)
    camelot = out.stdout.strip()
    if out.returncode != 0 or not camelot:
        return None
    return KeyResult(camelot=camelot, standard="", confidence=0.0,
                     source="keyfinder")
