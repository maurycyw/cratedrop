import numpy as np
import pytest

from cratedrop.analysis.beats import fit_constant_grid


def _quantized_beats(bpm: float, first_s: float, n: int, frame_s: float = 0.020):
    """Simulate beat-this output: true grid quantized to 20 ms frames."""
    true = first_s + np.arange(n) * 60.0 / bpm
    return np.round(true / frame_s) * frame_s


def test_fit_recovers_bpm_from_quantized_beats():
    beats = _quantized_beats(160.0, 0.5, 500)
    grid = fit_constant_grid(beats, beats[::4], duration_ms=190_000.0)
    assert grid.bpm == pytest.approx(160.0, abs=0.05)
    interval = 60_000.0 / grid.bpm
    delta = (500.0 - grid.first_beat_ms) % interval
    assert min(delta, interval - delta) < 15.0
    assert grid.confidence > 0.9


def test_fit_survives_double_fire_and_dropout():
    beats = _quantized_beats(160.0, 0.5, 500)
    beats = np.delete(beats, 100)                 # missed beat
    beats = np.sort(np.append(beats, beats[200] + 0.1))  # double-fire
    grid = fit_constant_grid(beats, beats[::4], duration_ms=190_000.0)
    assert grid.bpm == pytest.approx(160.0, abs=0.05)


def test_fit_odd_tempo():
    beats = _quantized_beats(149.97, 0.25, 400)
    grid = fit_constant_grid(beats, beats[::4], duration_ms=170_000.0)
    assert grid.bpm == pytest.approx(149.97, abs=0.05)
