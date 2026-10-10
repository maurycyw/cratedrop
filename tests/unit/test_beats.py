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


def test_two_tempo_edit_gets_segmented_grid():
    """A DJ edit: 128 BPM for 150 beats, hard cut to 150 BPM for 150 beats."""
    import numpy as np

    from cratedrop.analysis.beats import fit_grid

    a = _quantized_beats(128.0, 0.5, 150)
    b_start = a[-1] + 0.9  # cut: off-grid jump
    b = _quantized_beats(150.0, b_start, 150)
    beats = np.concatenate([a, b])
    grid = fit_grid(beats, beats[::4], duration_ms=float((b[-1] + 2) * 1000))

    times = np.array([x.time_ms for x in grid.beats])
    early = np.diff(times[times < a[-1] * 1000])
    late = np.diff(times[times > b_start * 1000])
    assert abs(60000.0 / np.median(early) - 128.0) < 0.05
    assert abs(60000.0 / np.median(late) - 150.0) < 0.05
    assert grid.confidence > 0.85


def test_constant_track_still_constant_through_fit_grid():
    import numpy as np

    from cratedrop.analysis.beats import fit_grid

    beats = _quantized_beats(160.0, 0.5, 400)
    grid = fit_grid(beats, beats[::4], duration_ms=float((beats[-1] + 1) * 1000))
    assert grid.bpm == pytest.approx(160.0, abs=0.05)
    ivals = np.diff([b.time_ms for b in grid.beats])
    assert np.allclose(ivals, ivals[0])  # one tempo end to end


def test_pqtz_carries_per_beat_tempo():
    from pyrekordbox.anlz import AnlzFile

    from cratedrop.formats.anlz import writer as w
    from cratedrop.model import Beat, BeatGrid, TrackAnalysis, TrackMeta

    beats = tuple(
        [Beat(time_ms=i * 500.0, beat_in_bar=i % 4 + 1) for i in range(32)]
        + [Beat(time_ms=16000.0 + (i + 1) * 400.0, beat_in_bar=i % 4 + 1)
           for i in range(32)])
    analysis = TrackAnalysis(
        meta=TrackMeta(source_path="/x.wav", title="X", duration_ms=40_000.0),
        grid=BeatGrid(bpm=120.0, first_beat_ms=0.0, beats=beats))
    parsed = AnlzFile.parse(w.build_dat(analysis, "/Contents/A/B/x.wav"))
    bpms = set(parsed.get_tag("PQTZ").get_bpms())
    assert 120.0 in bpms and 150.0 in bpms
