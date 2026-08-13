"""Time-domain windows with NI/LabVIEW-exact semantics.

SPWB used NI's ``Scaled Time Domain Window`` VI, whose behaviour this module
reproduces (validated bit-near against LabVIEW 2022 in the test suite):

* windows are **periodic** (DFT-even), w computed at 2*pi*i/N;
* the *scaled* window is amplitude-preserving: ``x * w / CG`` where the
  coherent gain ``CG = mean(w)``;
* window properties returned alongside: CG and the equivalent noise
  bandwidth ``ENBW = N * sum(w^2) / sum(w)^2`` (in bins), used later for
  PSD scaling and band power.

Window names follow SPWB's menu; Blackman-Nuttall exists here analytically
even though NI's VI exposed it at ring code 11 under the "Triangle" label
confusion (see port notes).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.signal import get_window as _scipy_get_window
from scipy.signal import windows as _sw

__all__ = ["WINDOW_NAMES", "WindowProps", "scaled_window", "window"]


@dataclass(frozen=True)
class WindowProps:
    """Constants of a window, as returned by NI's Scaled Time Domain Window."""
    eq_noise_bw: float   # ENBW in bins
    coherent_gain: float # CG = mean(w)


# cosine-sum coefficient tables: w[i] = sum_m (-1)^m a[m] cos(2 pi m i / N)
_COSINE_SUM: dict[str, tuple[float, ...]] = {
    "hanning": (0.5, 0.5),
    "hamming": (0.54, 0.46),
    # 3-term -67 dB Blackman-Harris
    "blackman_harris": (0.42323, 0.49755, 0.07922),
    "exact_blackman": (7938 / 18608, 9240 / 18608, 1430 / 18608),
    "blackman": (0.42, 0.50, 0.08),
    # NI flat top (recovered exactly from LabVIEW 2022; scipy's differ ~1e-8)
    "flat_top": (0.215578948, 0.416631580, 0.277263158, 0.083578947,
                 0.006947368),
    # 4-term -92 dB Blackman-Harris
    "bh_4term": (0.35875, 0.48829, 0.14128, 0.01168),
    "bh_7term": (0.27105140069342, 0.43329793923448, 0.21812299954311,
                 0.06592544638803, 0.01081174209837, 0.00077658482522,
                 0.00001388721735),
    "low_sidelobe": (0.323215218, 0.471492057, 0.17553428,
                     0.028497078, 0.001261367),
    "blackman_nuttall": (0.3635819, 0.4891775, 0.1365995, 0.0106411),
}

WINDOW_NAMES: tuple[str, ...] = (
    "rectangular", "hanning", "hamming", "blackman_harris", "exact_blackman",
    "blackman", "flat_top", "bh_4term", "bh_7term", "low_sidelobe",
    "blackman_nuttall", "triangle", "bartlett_hanning", "bohman", "parzen",
    "welch", "kaiser", "dolph_chebyshev", "gaussian",
)


def window(name: str, n: int, parameter: float = math.nan) -> np.ndarray:
    """Return the (unscaled, periodic) window ``w`` of length ``n``.

    ``parameter`` follows NI conventions: Kaiser beta (NaN -> 0), Gaussian
    relative standard deviation (NaN -> 0.2), Dolph-Chebyshev sidelobe
    ratio in dB (NaN -> 60). Other windows ignore it.
    """
    name = name.lower()
    if name == "rectangular":
        return np.ones(n)
    if name in _COSINE_SUM:
        a = _COSINE_SUM[name]
        k = 2.0 * np.pi * np.arange(n) / n
        w = np.zeros(n)
        for m, am in enumerate(a):
            w += ((-1.0) ** m) * am * np.cos(m * k)
        return w
    if name == "triangle":  # periodic Bartlett
        i = np.arange(n)
        return 1.0 - np.abs(i - n / 2.0) / (n / 2.0)
    if name == "welch":
        i = np.arange(n)
        return 1.0 - ((i - n / 2.0) / (n / 2.0)) ** 2
    if name == "bartlett_hanning":
        return _scipy_get_window("barthann", n, fftbins=True)
    if name == "bohman":
        return _scipy_get_window("bohman", n, fftbins=True)
    if name == "parzen":
        # NI's parzen: piecewise cubic on q = |i - n/2| / (n/2)
        q = np.abs(np.arange(n) - n / 2.0) / (n / 2.0)
        return np.where(q <= 0.5, 1 - 6 * q**2 + 6 * q**3, 2 * (1 - q)**3)
    if name == "kaiser":
        beta = 0.0 if math.isnan(parameter) else float(parameter)
        return _sw.kaiser(n, beta, sym=False)
    if name == "dolph_chebyshev":
        at = 60.0 if math.isnan(parameter) else float(parameter)
        return _sw.chebwin(n, at, sym=False)
    if name == "gaussian":
        # NI's gaussian: symmetric over n+1 points truncated to n,
        # with sigma = std * (n + 1)
        std = 0.2 if math.isnan(parameter) else float(parameter)
        if std <= 0:
            raise ValueError("gaussian window parameter (std) must be > 0")
        return _sw.gaussian(n + 1, std * (n + 1))[:n]
    raise ValueError(f"unknown window {name!r}; expected one of {WINDOW_NAMES}")


def props(w: np.ndarray) -> WindowProps:
    n = len(w)
    s = w.sum()
    return WindowProps(eq_noise_bw=n * float((w ** 2).sum()) / float(s * s),
                       coherent_gain=float(s) / n)


def scaled_window(x: np.ndarray, name: str,
                  parameter: float = math.nan) -> tuple[np.ndarray, WindowProps]:
    """NI ``Scaled Time Domain Window``: amplitude-preserving windowing.

    Returns ``x * w / CG`` and the window properties.
    """
    x = np.asarray(x, dtype=float)
    w = window(name, len(x), parameter)
    p = props(w)
    return x * w / p.coherent_gain, p
