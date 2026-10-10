"""Beatgrid detection: Beat This! (CPJKU) beats + downbeats → constant grid.

Stage 1 scope is constant-tempo material: we reduce the tracker's beat list
to a single BPM (median inter-beat interval, refined by least squares) and a
phase, anchored so beat 1 of each bar lands on the detected downbeats.
Confidence = fraction of detected beats within 30 ms of the fitted grid.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from ..model import BeatGrid

DETECTOR_SAMPLE_RATE = 22050  # beat-this resamples internally; feed it our PCM


@lru_cache(maxsize=1)
def _audio2beats():
    from beat_this.inference import Audio2Beats

    return Audio2Beats(checkpoint_path="final0", device="cpu", dbn=False)


def detect_grid(samples: np.ndarray, sample_rate: int,
                duration_ms: float) -> BeatGrid:
    """samples: mono float PCM. Returns a constant BeatGrid."""
    beats, downbeats = _audio2beats()(samples.astype(np.float32), sample_rate)
    if len(beats) < 8:
        raise RuntimeError(f"beat tracker found only {len(beats)} beats")
    return fit_grid(np.asarray(beats), np.asarray(downbeats), duration_ms,
                    samples=samples, sample_rate=sample_rate)


def fit_constant_grid(beats_s: np.ndarray, downbeats_s: np.ndarray,
                      duration_ms: float, samples: np.ndarray | None = None,
                      sample_rate: int = DETECTOR_SAMPLE_RATE) -> BeatGrid:
    """Reduce detected beats (seconds) to a constant grid.

    1. interval from the median inter-beat gap (robust to octave-consistent
       outliers), refined by a least-squares fit of beat time vs beat index
       over the central 80% of beats (skips sloppy intro/outro detections);
    2. phase from the median residual;
    3. bar phase (which grid line is beat 1) voted by the downbeats.
    """
    beats_s = np.sort(beats_s)
    interval = float(np.median(np.diff(beats_s)))

    # Remove double-fires: a beat closer than 0.6 intervals to its
    # predecessor is spurious and would shift every later grid index.
    keep = [0]
    for i in range(1, len(beats_s)):
        if beats_s[i] - beats_s[keep[-1]] >= 0.6 * interval:
            keep.append(i)
    beats_s = beats_s[keep]

    # Fit tempo on the LONGEST STEADY RUN of beats. DJ edits and mashups have
    # sections where the grid phase jumps (cut beats); a global fit over such
    # a mixture lands between tempos. The steady run is the track's true grid.
    ibis = np.diff(beats_s)
    ok = np.abs(ibis - interval) < max(0.025, 0.08 * interval)
    best_start = best_len = cur_start = cur_len = 0
    for i, flag in enumerate(ok):
        if flag:
            cur_len += 1
            if cur_len > best_len:
                best_len, best_start = cur_len, cur_start
        else:
            cur_start, cur_len = i + 1, 0
    run = beats_s[best_start:best_start + best_len + 1] if best_len >= 16 else beats_s

    # beat-this quantizes beat times to 20 ms frames, so the median IBI is
    # biased to a frame multiple (e.g. 380 ms for a true 375 ms / 160 BPM).
    # Assign grid indices INCREMENTALLY (per-IBI rounding never accumulates
    # error), then least-squares index->time to average the quantization out.
    for _ in range(2):
        steps = np.maximum(1, np.round(np.diff(run) / interval)).astype(int)
        idx = np.concatenate([[0], np.cumsum(steps)])
        slope, intercept = np.polyfit(idx, run, 1)
        interval = float(slope)
    bpm = round(60.0 / interval, 2)
    interval = 60.0 / bpm  # exact interval for the 2-decimal BPM we store
    beats_for_phase = run

    # phase: median residual against the refined interval, over the steady run
    residuals = beats_for_phase - (np.round((beats_for_phase - intercept) / interval)
                                   * interval + intercept)
    phase = float(intercept + np.median(residuals))

    # Anchor the first grid point on the first AUDIBLE beat (Rekordbox
    # convention). Beat trackers emit spurious edge beats near t=0, so decide
    # by signal energy at candidate grid lines rather than trusting the first
    # detection.
    first = phase - np.floor(phase / interval) * interval
    if first < 0:
        first += interval
    # NOTE on half-beat phase: on a few tracks the tracker's phase differs
    # from Rekordbox's stored grid by exactly half a beat. Onset-based
    # disambiguation was tried and proved too fragile (features separate by
    # <2x and invert under small phase error), so we trust the tracker; a
    # wrong call is fixable per-track via manual override.
    if samples is not None and len(samples):
        window = max(1, int(0.080 * sample_rate))
        hop = max(1, window // 4)
        frames = np.lib.stride_tricks.sliding_window_view(samples, window)[::hop]
        frame_rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
        threshold = 0.15 * np.percentile(frame_rms, 95)
        t = first
        while t < duration_ms / 1000.0 - 0.1:
            start = int(t * sample_rate)
            seg = samples[start:start + window]
            if len(seg) and np.sqrt((seg.astype(np.float64) ** 2).mean()) >= threshold:
                break
            t += interval
        first = t
    else:
        first = phase + round((beats_s[0] - phase) / interval) * interval
        if first < 0:
            first += interval

    # bar phase: which (grid index mod 4) do downbeats land on
    if len(downbeats_s):
        db_idx = np.round((np.asarray(downbeats_s) - first) / interval).astype(int) % 4
        bar_offset = int(np.bincount(db_idx, minlength=4).argmax())
    else:
        bar_offset = 0
    # beat_in_bar of the FIRST grid point: downbeat at offset k means grid
    # point k is beat 1, so point 0 is beat (4 - k) steps before a "1"
    first_beat_in_bar = (0 - bar_offset) % 4 + 1

    grid = BeatGrid.constant(bpm=bpm, first_beat_ms=first * 1000.0,
                             duration_ms=duration_ms,
                             first_beat_in_bar=first_beat_in_bar)
    # Confidence = fraction of ALL detected beats within 30 ms of the grid
    err = np.abs(((beats_s - phase + interval / 2) % interval) - interval / 2)
    confidence = float((err < 0.030).mean())
    return BeatGrid(bpm=grid.bpm, first_beat_ms=grid.first_beat_ms,
                    beats=grid.beats, confidence=confidence)


# ── variable tempo ───────────────────────────────────────────────────────────


def _steady_runs(beats_s: np.ndarray) -> list[tuple[int, int]]:
    """Maximal runs [i, j] (beat indexes, inclusive) whose inter-beat
    intervals stay near the run's own local tempo. DJ edits and multi-tempo
    sets break into several runs."""
    ibis = np.diff(beats_s)
    runs: list[tuple[int, int]] = []
    start = 0
    for i in range(1, len(ibis)):
        local = float(np.median(ibis[start:i]))
        if abs(float(ibis[i]) - local) > max(0.025, 0.08 * local):
            if i - start >= 15:  # >= 16 beats
                runs.append((start, i))
            start = i + 1
    if len(ibis) - start >= 15:
        runs.append((start, len(ibis)))
    return runs


def _fit_segment(seg: np.ndarray) -> tuple[float, float, float]:
    """(interval_s, anchor_s, median_abs_residual_s) for one steady run."""
    interval = float(np.median(np.diff(seg)))
    for _ in range(2):
        steps = np.maximum(1, np.round(np.diff(seg) / interval)).astype(int)
        idx = np.concatenate([[0], np.cumsum(steps)])
        slope, intercept = np.polyfit(idx, seg, 1)
        interval = float(slope)
    bpm = round(60.0 / interval, 2)
    interval = 60.0 / bpm
    resid = seg - (np.round((seg - intercept) / interval) * interval + intercept)
    phase = float(intercept + np.median(resid))
    anchor = phase + round((seg[0] - phase) / interval) * interval
    quality = float(np.median(np.abs(resid - np.median(resid))))
    return interval, anchor, quality


def fit_grid(beats_s: np.ndarray, downbeats_s: np.ndarray, duration_ms: float,
             samples: np.ndarray | None = None,
             sample_rate: int = DETECTOR_SAMPLE_RATE) -> BeatGrid:
    """Constant grid when one tempo covers the track; otherwise a segmented
    (piecewise-constant) grid — DJ edits with cut beats, multi-tempo sets."""
    beats_s = np.sort(beats_s)
    med = float(np.median(np.diff(beats_s)))
    keep = [0]
    for i in range(1, len(beats_s)):
        if beats_s[i] - beats_s[keep[-1]] >= 0.6 * med:
            keep.append(i)
    beats_s = beats_s[keep]

    runs = _steady_runs(beats_s)
    total = len(beats_s)
    if not runs or (max(j - i + 1 for i, j in runs) / total) >= 0.90 or len(runs) == 1:
        return fit_constant_grid(beats_s, downbeats_s, duration_ms,
                                 samples=samples, sample_rate=sample_rate)

    from ..model import Beat
    from ..model import BeatGrid as _BG

    # Merge adjacent runs whose tempo agrees within 1%: they are one tempo
    # split by a bad beat, and the joint fit averages the tracker's 20 ms
    # frame quantization out far better than two short fits.
    fitted: list[tuple[int, int, float]] = []
    for i, j in runs:
        interval, _, _ = _fit_segment(beats_s[i:j + 2])  # j is an IBI index
        if fitted and abs(interval - fitted[-1][2]) / fitted[-1][2] < 0.01:
            pi, _, _ = fitted[-1]
            joint, _, quality = _fit_segment(beats_s[pi:j + 2])
            # merge only if one grid truly spans both runs (no phase jump
            # hiding in the gap) — otherwise keep them separate
            if quality < 0.012:
                fitted[-1] = (pi, j, joint)
                continue
        fitted.append((i, j, interval))

    segments = []
    for i, j, _ in fitted:
        interval, anchor, _ = _fit_segment(beats_s[i:j + 2])
        segments.append((anchor, interval))
    segments.sort()

    grid: list[Beat] = []
    for k, (anchor, interval) in enumerate(segments):
        end = segments[k + 1][0] - interval * 0.5 if k + 1 < len(segments)             else duration_ms / 1000.0
        times = np.arange(anchor, end, interval)
        if not len(times):
            continue
        # bar phase per segment: vote the detected downbeats inside it
        db = downbeats_s[(downbeats_s >= anchor - interval / 2)
                         & (downbeats_s < end)] if len(downbeats_s) else []
        if len(db):
            offs = np.round((np.asarray(db) - anchor) / interval).astype(int) % 4
            bar_offset = int(np.bincount(offs, minlength=4).argmax())
        else:
            bar_offset = 0
        for n, t in enumerate(times):
            grid.append(Beat(time_ms=float(t * 1000.0),
                             beat_in_bar=(n - bar_offset) % 4 + 1))

    grid.sort(key=lambda b: b.time_ms)
    # dominant bpm = tempo of the segment covering the most time
    spans = []
    for k, (anchor, interval) in enumerate(segments):
        end = segments[k + 1][0] if k + 1 < len(segments) else duration_ms / 1000.0
        spans.append((end - anchor, interval))
    dominant_interval = max(spans)[1]
    bpm = round(60.0 / dominant_interval, 2)

    grid_times = np.array([b.time_ms for b in grid]) / 1000.0
    if len(grid_times):
        idx = np.clip(np.searchsorted(grid_times, beats_s), 1, len(grid_times) - 1)
        err = np.minimum(np.abs(beats_s - grid_times[idx]),
                         np.abs(beats_s - grid_times[idx - 1]))
        confidence = float((err < 0.030).mean())
    else:
        confidence = 0.0
    first = grid[0].time_ms if grid else 0.0
    return _BG(bpm=bpm, first_beat_ms=first, beats=tuple(grid),
               confidence=confidence)
