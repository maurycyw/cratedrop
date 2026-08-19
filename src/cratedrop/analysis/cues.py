"""Heuristic hot cue placement, all snapped to downbeats.

  A (green)  — first kick: first bar with real low-band energy
  B (red)    — drop: strongest sustained low-band rise vs the preceding bars
  C (yellow) — breakdown: lowest-energy 8-bar window after the drop
  D (blue)   — outro: 16 bars (64 beats) before the end of energy

Operates purely on WaveformData (150 bins/s band energies) + the fitted grid;
no extra DSP. Produces HEURISTIC cues — merge_cues() guarantees they never
displace deck- or user-set cues.
"""

from __future__ import annotations

import numpy as np

from ..model import BeatGrid, CueKind, CuePoint, CueSource, WaveformData


def place_cues(grid: BeatGrid, waveform: WaveformData) -> tuple[CuePoint, ...]:
    downbeats = [b.time_ms for b in grid.beats if b.beat_in_bar == 1]
    if len(downbeats) < 8:
        return ()
    low = np.asarray(waveform.low)
    rms = np.asarray(waveform.rms)
    bps = waveform.bins_per_second

    def window_mean(arr: np.ndarray, start_ms: float, end_ms: float) -> float:
        i0 = max(0, int(start_ms / 1000 * bps))
        i1 = min(len(arr), max(i0 + 1, int(end_ms / 1000 * bps)))
        return float(arr[i0:i1].mean()) if i0 < len(arr) else 0.0

    bar_ms = 4 * 60_000.0 / grid.bpm
    bar_low = np.array([window_mean(low, t, t + bar_ms) for t in downbeats])
    bar_rms = np.array([window_mean(rms, t, t + bar_ms) for t in downbeats])
    n = len(downbeats)

    cues: dict[str, tuple[float, str]] = {}

    # A: first kick
    kick_threshold = 0.25 * np.percentile(bar_low, 95)
    kicks = np.flatnonzero(bar_low >= kick_threshold)
    a_bar = int(kicks[0]) if len(kicks) else 0
    cues["A"] = (downbeats[a_bar], "KICK IN")

    # B: drop — sustained rise vs preceding 8 bars, searched after A
    b_bar = None
    search = range(a_bar + 4, max(a_bar + 5, int(n * 0.75)))
    best = 0.0
    for i in search:
        if i + 4 > n:
            break
        rise = bar_low[i:i + 4].mean() - bar_low[max(0, i - 8):i].mean()
        if rise > best:
            best, b_bar = rise, i
    if b_bar is not None and best > 0.05 * np.percentile(bar_low, 95):
        cues["B"] = (downbeats[b_bar], "DROP")

    # C: breakdown — lowest-energy 8-bar window after the drop (or after A)
    start = (b_bar if b_bar is not None else a_bar) + 4
    if start + 8 < n - 4:
        windows = np.array([bar_rms[i:i + 8].mean() for i in range(start, n - 8)])
        c_bar = start + int(windows.argmin())
        if bar_rms[c_bar] < 0.8 * np.median(bar_rms[bar_rms > 0]):
            cues["C"] = (downbeats[c_bar], "BREAK")

    # D: outro — 16 bars before the last energetic bar
    active = np.flatnonzero(bar_rms >= 0.15 * np.percentile(bar_rms, 95))
    last_bar = int(active[-1]) if len(active) else n - 1
    d_bar = max(a_bar, last_bar - 16)
    cues["D"] = (downbeats[d_bar], "OUTRO")

    # drop coincident/out-of-order duplicates (keep earlier slots)
    result, used_times = [], []
    for slot in "ABCD":
        if slot not in cues:
            continue
        time_ms, label = cues[slot]
        if any(abs(time_ms - u) < bar_ms / 2 for u in used_times):
            continue
        used_times.append(time_ms)
        result.append(CuePoint(kind=CueKind.HOT, slot=slot, time_ms=time_ms,
                               label=label, source=CueSource.HEURISTIC))
    return tuple(sorted(result, key=lambda c: c.slot))
