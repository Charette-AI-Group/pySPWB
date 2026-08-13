"""Time-frequency analysis - port of SPWB's STFT spectrogram.

Ported from (LabVIEW block diagrams in SPWB_export):
  * ``STFT - Spectogram.vi``                  -> :func:`stft_spectrogram`
  * ``Time Frequency Analysis (V1.25).vit``   -> the TFA window's controls

The numerical convention was recovered by calling NI's
``TFA STFT Spectrogram (Real).vi`` over COM and probing it (see
``tools/make_stft_fixtures.py``); it is **not** the same as
``scipy.signal.spectrogram``'s default:

* frames are **centre-aligned** - the signal is pre-padded by ``nfft//2``,
  so frame *i* is centred on sample ``i * hop``;
* there are ``len(x) // hop + 1`` frames, i.e. NI's "time steps" input is
  the **hop in samples**, not a number of frames;
* ``nfft//2`` single-sided bins are returned, **without** the factor-2
  doubling the auto-power path applies;
* each bin is ``|FFT(w·x)|² / (Σw² · nfft)``, a power quantity: a sine of
  amplitude A through a rectangular window peaks at ``A²/4``.

SPWB's panel exposes a single "FFT block size", so the window length and
the FFT length are always equal here, as in the original application.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..model.signal import Signal
from . import windows as _win

__all__ = [
    "COLOR_TABLES",
    "TFA_WINDOW_RING",
    "Spectrogram",
    "stft_spectrogram",
]

#: ``Color Table`` on the TFA panel
COLOR_TABLES: tuple[str, ...] = ("rainbow", "fire", "gray", "viridis")

#: NI's TFA window ring -> spwb window name (probed against LabVIEW 2022)
TFA_WINDOW_RING: dict[int, str] = {
    0: "rectangular", 1: "hanning", 2: "hamming", 3: "blackman_harris",
    4: "exact_blackman", 5: "blackman", 6: "flat_top", 7: "bh_4term",
}


@dataclass(frozen=True)
class Spectrogram:
    """A time-frequency map plus the axes needed to plot and slice it."""

    data: np.ndarray        # (n_frames, n_bins), power
    times: np.ndarray       # seconds, one per frame (frame centre)
    freqs: np.ndarray       # Hz, one per bin
    name: str = ""
    y_unit: str = ""
    attributes: dict | None = None

    @property
    def shape(self) -> tuple[int, int]:
        return self.data.shape

    @property
    def n_frames(self) -> int:
        return self.data.shape[0]

    @property
    def n_bins(self) -> int:
        return self.data.shape[1]

    @property
    def df(self) -> float:
        return float(self.freqs[1] - self.freqs[0]) if len(self.freqs) > 1 else 0.0

    @property
    def dt(self) -> float:
        return float(self.times[1] - self.times[0]) if len(self.times) > 1 else 0.0

    # -- the two cross sections the TFA panel shows -------------------------
    def time_section(self, time: float) -> Signal:
        """Spectrum at the frame nearest ``time`` (the panel's Time Section)."""
        i = int(np.argmin(np.abs(self.times - time)))
        return Signal(
            name=f"{self.name} @ {self.times[i]:.4g} s",
            y=self.data[i].copy(), dt=self.df or 1.0, t0=float(self.freqs[0]),
            y_unit=self.y_unit, x_unit="Hz",
            attributes={"TFA_Section": "time", "TFA_Time": float(self.times[i])},
        )

    def frequency_section(self, freq: float) -> Signal:
        """Level over time at the bin nearest ``freq`` (Frequency Section)."""
        j = int(np.argmin(np.abs(self.freqs - freq)))
        return Signal(
            name=f"{self.name} @ {self.freqs[j]:.6g} Hz",
            y=self.data[:, j].copy(), dt=self.dt or 1.0,
            t0=float(self.times[0]),
            y_unit=self.y_unit, x_unit="sec",
            attributes={"TFA_Section": "frequency",
                        "TFA_Frequency": float(self.freqs[j])},
        )

    def to_db(self, reference: float | None = None,
              dynamic_range: float = 100.0) -> Spectrogram:
        """Convert to dB, floored ``dynamic_range`` below the peak.

        The TFA panel's dB toggle. Flooring keeps empty bins from becoming
        -inf and destroying the colour scale.
        """
        peak = float(self.data.max()) if self.data.size else 0.0
        ref = float(reference) if reference is not None else (peak or 1.0)
        if ref <= 0:
            ref = 1.0
        floor = ref * 10.0 ** (-dynamic_range / 10.0)
        clipped = np.maximum(self.data, max(floor, np.finfo(float).tiny))
        return Spectrogram(
            data=10.0 * np.log10(clipped / ref),
            times=self.times, freqs=self.freqs, name=self.name,
            y_unit="dB", attributes={**(self.attributes or {}),
                                     "TFA_dB_Reference": ref},
        )


def stft_spectrogram(signal: Signal, *,
                     block_size: int = 1024,
                     hop: int | None = None,
                     window: str = "hanning",
                     window_parameter: float = math.nan,
                     normalize: bool = False) -> Spectrogram:
    """STFT spectrogram of one signal, NI/SPWB convention.

    Parameters
    ----------
    block_size:
        SPWB's "FFT block size": both the window length and the FFT length.
        Must be even and no longer than the signal.
    hop:
        Samples between frame centres (NI's "time steps"). Defaults to
        ``block_size // 4``, giving 75% overlap.
    normalize:
        Scale the signal to unit peak first (the panel's "Norm Signal").
    """
    block_size = int(block_size)
    if block_size < 2 or block_size % 2:
        raise ValueError(f"block_size must be even and >= 2, got {block_size}")
    if block_size > signal.n_samples:
        raise ValueError(
            f"block_size {block_size} exceeds the signal length "
            f"({signal.n_samples} samples)")
    step = int(hop) if hop is not None else max(1, block_size // 4)
    if step < 1:
        raise ValueError(f"hop must be >= 1, got {step}")

    y = np.asarray(signal.y, dtype=float)
    if normalize:
        peak = float(np.max(np.abs(y)))
        if peak > 0:
            y = y / peak

    w = _win.window(window, block_size, window_parameter)
    half = block_size // 2
    denominator = float((w ** 2).sum()) * block_size

    # centre-align: frame i is centred on sample i*hop
    padded = np.concatenate([np.zeros(half), y, np.zeros(block_size)])
    n_frames = len(y) // step + 1
    data = np.empty((n_frames, half))
    for i in range(n_frames):
        segment = padded[i * step: i * step + block_size]
        spectrum = np.fft.rfft(segment * w)
        data[i] = np.abs(spectrum[:half]) ** 2 / denominator

    times = signal.t0 + np.arange(n_frames) * step * signal.dt
    freqs = np.arange(half) * (signal.fs / block_size)
    unit = signal.y_unit or "EU"
    return Spectrogram(
        data=data, times=times, freqs=freqs, name=signal.name,
        y_unit=f"{unit}²",
        attributes={
            **signal.attributes,
            "TFA_Block_Size": block_size,
            "TFA_Hop": step,
            "TFA_Window_Type": window,
            "TFA_Normalized": bool(normalize),
            "X_UnitDescription": "sec",
        },
    )
