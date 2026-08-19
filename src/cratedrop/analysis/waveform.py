"""Waveform analysis: per-bin peak/RMS + 3-band energies → WaveformData.

Bands come from a real Butterworth filterbank (low <105 Hz, mid 105–980 Hz,
high >980 Hz — the crossovers Pioneer-style waveforms use), with per-band
p95 normalization. Calibrated against golden Rekordbox ANLZ output for the
same audio: raw band RMS has bass >> mid >> treble by an order of magnitude,
while native color waveforms show the three channels roughly balanced —
normalization is what makes our colors match the deck's rendering.
150 bins/s matches Pioneer scroll waveform resolution exactly.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from ..model import WaveformData

BINS_PER_SECOND = 150
SAMPLE_RATE = 22050
SAMPLES_PER_BIN = round(SAMPLE_RATE / BINS_PER_SECOND)  # 147

LOW_HZ = 105.0
HIGH_HZ = 980.0
# Per-band value at the 95th percentile after normalization. The quantizers
# multiply by 28 (PWV5, 3-bit) and 510 (PWV4/6/7, 8-bit); 0.20 puts p95 at
# ~5.6/7 and ~102/255, matching golden channel statistics.
BAND_P95_TARGET = 0.20

_SOS_LOW = butter(4, LOW_HZ, "lowpass", fs=SAMPLE_RATE, output="sos")
_SOS_MID = butter(4, [LOW_HZ, HIGH_HZ], "bandpass", fs=SAMPLE_RATE, output="sos")
_SOS_HIGH = butter(4, HIGH_HZ, "highpass", fs=SAMPLE_RATE, output="sos")


def analyze_waveform(samples: np.ndarray) -> WaveformData:
    """samples: mono float array at SAMPLE_RATE."""
    n_bins = len(samples) // SAMPLES_PER_BIN
    if n_bins == 0:
        raise ValueError("audio shorter than one waveform bin")
    trimmed = samples[:n_bins * SAMPLES_PER_BIN]

    def per_bin_rms(x: np.ndarray) -> np.ndarray:
        r = x.reshape(n_bins, SAMPLES_PER_BIN)
        return np.sqrt((r * r).mean(axis=1))

    def band(sos) -> np.ndarray:
        vals = per_bin_rms(sosfilt(sos, trimmed))
        p95 = np.percentile(vals, 95)
        if p95 <= 0:
            return vals
        return vals * (BAND_P95_TARGET / p95)

    peaks = np.abs(trimmed).reshape(n_bins, SAMPLES_PER_BIN).max(axis=1)
    return WaveformData(
        bins_per_second=BINS_PER_SECOND,
        peak=tuple(peaks.tolist()),
        rms=tuple(per_bin_rms(trimmed).tolist()),
        low=tuple(band(_SOS_LOW).tolist()),
        mid=tuple(band(_SOS_MID).tolist()),
        high=tuple(band(_SOS_HIGH).tolist()),
    )
