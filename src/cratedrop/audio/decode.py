"""Audio decoding: mono float PCM for analysis.

soundfile (libsndfile >= 1.1) covers wav/aiff/flac/mp3; anything it can't
open falls back to an ffmpeg subprocess.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

ANALYSIS_SAMPLE_RATE = 22050  # sufficient for waveforms and band energies

AUDIO_SUFFIXES = {".mp3", ".wav", ".aiff", ".aif", ".flac"}


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_SUFFIXES


def decode_mono(path: Path, sample_rate: int = ANALYSIS_SAMPLE_RATE) -> np.ndarray:
    """Decode to mono float64 at the given rate."""
    try:
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        mono = data.mean(axis=1).astype(np.float64)
        if sr != sample_rate:
            # linear resample is plenty for energy analysis
            n_out = int(round(len(mono) * sample_rate / sr))
            x_old = np.linspace(0.0, 1.0, num=len(mono), endpoint=False)
            x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
            mono = np.interp(x_new, x_old, mono)
        return mono
    except Exception:  # noqa: BLE001 - fall through to ffmpeg
        return _decode_ffmpeg(path, sample_rate)


def _decode_ffmpeg(path: Path, sample_rate: int) -> np.ndarray:
    proc = subprocess.run(
        ["ffmpeg", "-i", str(path), "-f", "f32le", "-ac", "1",
         "-ar", str(sample_rate), "-loglevel", "error", "pipe:1"],
        capture_output=True, check=False)
    if proc.returncode != 0 and not proc.stdout:
        raise RuntimeError(
            f"ffmpeg failed to decode {path}: {proc.stderr.decode(errors='replace')[:200]}")
    return np.frombuffer(proc.stdout, dtype=np.float32).astype(np.float64)
