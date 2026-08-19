"""Generate deterministic test audio fixtures.

Run: uv run python tests/fixtures/audio/generate.py

click_120bpm.wav — 2 minutes at exactly 120 BPM, first kick at exactly 500 ms.
Kick on every beat (low thump), accent + hi click on every downbeat (beat 1),
plus a quiet sustained bass line so waveforms/key detectors have content.
Ground truth for analysis tests: bpm=120.0, first_beat_ms=500.0, downbeats at
500 + k*2000 ms, key ~ A minor (bass alternates A1/E2/C2/E2).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
BPM = 120.0
FIRST_BEAT_S = 0.5
DURATION_S = 120.0


def _kick(t: np.ndarray, f0: float = 120.0, decay: float = 18.0) -> np.ndarray:
    """Percussive sine sweep, exponential decay — a synthetic kick drum."""
    freq = f0 * np.exp(-t * 8) + 45.0
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return np.sin(phase) * np.exp(-t * decay)


def _click(t: np.ndarray) -> np.ndarray:
    return np.sin(2 * np.pi * 2500 * t) * np.exp(-t * 120.0)


def main() -> None:
    out_dir = Path(__file__).parent
    n = int(DURATION_S * SR)
    audio = np.zeros(n, dtype=np.float64)

    beat_interval = 60.0 / BPM
    # A natural-minor-ish bass loop over one bar: A1, E2, C2, E2
    bass_freqs = [55.0, 82.41, 65.41, 82.41]

    beat = 0
    t_beat = FIRST_BEAT_S
    while t_beat < DURATION_S:
        start = int(t_beat * SR)
        seg = np.arange(min(n - start, int(0.35 * SR))) / SR
        audio[start:start + len(seg)] += _kick(seg) * (1.0 if beat % 4 == 0 else 0.8)
        if beat % 4 == 0:
            audio[start:start + len(seg)] += _click(seg) * 0.5
        # bass note held for the whole beat, keyed to position in bar
        bass_len = min(n - start, int(beat_interval * SR))
        tb = np.arange(bass_len) / SR
        env = np.minimum(1.0, tb / 0.02) * np.exp(-tb * 1.5)
        audio[start:start + bass_len] += 0.22 * np.sin(
            2 * np.pi * bass_freqs[beat % 4] * tb) * env
        beat += 1
        t_beat = FIRST_BEAT_S + beat * beat_interval

    audio /= np.max(np.abs(audio)) * 1.05
    stereo = np.column_stack([audio, audio]).astype(np.float32)
    path = out_dir / "click_120bpm.wav"
    sf.write(path, stereo, SR, subtype="PCM_16")
    print(f"wrote {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
