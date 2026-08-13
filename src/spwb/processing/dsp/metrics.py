"""Signal statistics and time-varying metrics.

Ported from (LabVIEW block diagrams in SPWB_export):
  * ``SA Cond - Time Varying Metrics.vi``       -> :func:`time_varying_metric`
  * ``SA Math - Signals Basic Statistics.vi``   -> :func:`signal_statistics`

**The normalisation quirk.** SPWB builds these trends from two NI
primitives that do *not* agree with each other, and reproducing that is the
whole point of this module:

* ``Moment about Mean.vi`` divides by **N** (population moment);
* ``Std Deviation and Variance.vi`` divides by **N-1** (sample variance).

So ``Variance`` and ``Standard Deviation`` are the sample forms, while
``Skewness`` = ``m3/σ³`` and ``Kurtosis`` = ``m4/σ⁴`` mix a population
moment with a sample sigma. Both conventions were confirmed by calling the
NI VIs over COM (see the tests). Kurtosis is *not* excess kurtosis - there
is no ``- 3``, so a Gaussian reads about 3.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..model.signal import Signal

__all__ = [
    "TREND_TYPES",
    "SignalStatistics",
    "signal_statistics",
    "time_varying_metric",
    "trend_value",
]

#: ``Trend Type`` on the TV Metrics tab, in the LabVIEW ring's order
TREND_TYPES: tuple[str, ...] = (
    "RMS",
    "Absolute Peak",
    "Range",
    "Standard Deviation",
    "Variance",
    "Skewness",
    "Kurtosis",
)


def trend_value(x: np.ndarray, trend: str) -> float:
    """One trend metric over a block of samples."""
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return float("nan")
    if trend == "RMS":
        return float(np.sqrt(np.mean(x * x)))
    if trend == "Absolute Peak":
        return float(np.max(np.abs(x)))
    if trend == "Range":
        return float(np.max(x) - np.min(x))
    if trend in ("Standard Deviation", "Variance", "Skewness", "Kurtosis"):
        if x.size < 2:
            return float("nan")             # sample variance is undefined
        variance = float(np.var(x, ddof=1))  # NI: /(N-1)
        if trend == "Variance":
            return variance
        sigma = np.sqrt(variance)
        if trend == "Standard Deviation":
            return float(sigma)
        if sigma == 0.0:
            return float("nan")
        order = 3 if trend == "Skewness" else 4
        moment = float(np.mean((x - x.mean()) ** order))   # NI: /N
        return moment / sigma ** order
    raise ValueError(f"unknown trend type {trend!r}; "
                     f"expected one of {TREND_TYPES}")


def time_varying_metric(signal: Signal, trend: str = "RMS", *,
                        step_ms: float = 1000.0,
                        length_ms: float = 1000.0,
                        annotate: bool = False) -> Signal:
    """Slide a window over the signal and report ``trend`` for each position.

    ``length_ms`` is the integration length of each window and ``step_ms``
    how far the window slides between points, both in milliseconds as the
    panel spells them. The result is a Signal sampled at ``step_ms``, so it
    plots against the original time axis.

    ``annotate`` appends ``(TVM)`` to the name, as the VI's
    "Anotate Signal Name" input does.
    """
    if trend not in TREND_TYPES:
        raise ValueError(f"unknown trend type {trend!r}; "
                         f"expected one of {TREND_TYPES}")
    if step_ms <= 0 or length_ms <= 0:
        raise ValueError("step_ms and length_ms must be positive")

    n_step = max(1, int(round(step_ms / 1000.0 / signal.dt)))
    n_window = max(1, int(round(length_ms / 1000.0 / signal.dt)))
    if n_window > signal.n_samples:
        raise ValueError(
            f"length {length_ms:g} ms needs {n_window} samples but the "
            f"signal has {signal.n_samples}")

    n_points = (signal.n_samples - n_window) // n_step + 1
    y = np.empty(n_points)
    for i in range(n_points):
        start = i * n_step
        y[i] = trend_value(signal.y[start:start + n_window], trend)

    name = f"{signal.name} (TVM)" if annotate else signal.name
    # the trend is unitless for the shape metrics, and keeps the signal's
    # unit (or its square) for the level ones
    if trend in ("Skewness", "Kurtosis"):
        unit = ""
    elif trend == "Variance":
        unit = f"{signal.y_unit}²" if signal.y_unit else ""
    else:
        unit = signal.y_unit

    return Signal(
        name=name,
        y=y,
        dt=n_step * signal.dt,
        # each point summarises a window; place it at the window's centre
        t0=signal.t0 + (n_window - 1) / 2.0 * signal.dt,
        y_unit=unit,
        x_unit=signal.x_unit,
        attributes={
            **signal.attributes,
            "Channel Name": name,
            "TVM_Trend_Type": trend,
            "TVM_Step_ms": float(step_ms),
            "TVM_Length_ms": float(length_ms),
            "TVM_Window_Samples": n_window,
            "TVM_Step_Samples": n_step,
        },
    )


@dataclass(frozen=True)
class SignalStatistics:
    """One row of the Stats tab (``SA Math - Signals Basic Statistics.vi``)."""

    name: str
    minimum: float
    maximum: float
    rms: float
    mean: float
    n_samples: int
    duration_ms: float
    unit: str = ""

    @property
    def peak_to_peak(self) -> float:
        return self.maximum - self.minimum

    @property
    def crest_factor(self) -> float:
        """Peak / RMS - the classic impulsiveness indicator."""
        peak = max(abs(self.maximum), abs(self.minimum))
        return peak / self.rms if self.rms else float("nan")


def signal_statistics(signal: Signal) -> SignalStatistics:
    """Min, max, RMS, mean, length and duration for one signal."""
    y = np.asarray(signal.y, dtype=float)
    return SignalStatistics(
        name=signal.name,
        minimum=float(np.min(y)) if y.size else float("nan"),
        maximum=float(np.max(y)) if y.size else float("nan"),
        rms=float(np.sqrt(np.mean(y * y))) if y.size else float("nan"),
        mean=float(np.mean(y)) if y.size else float("nan"),
        n_samples=signal.n_samples,
        duration_ms=signal.duration * 1000.0,
        unit=signal.y_unit,
    )
