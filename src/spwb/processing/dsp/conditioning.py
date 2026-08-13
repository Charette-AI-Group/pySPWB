"""Signal conditioning - the Scale Signals tab and friends.

Ported from (LabVIEW block diagrams in SPWB_export):
  * ``SA Math - Scale Signals.vi`` / ``Math - Scale Signals.vi``  -> :func:`scale`
  * ``SA Math - Offset Signals.vi``                              -> :func:`offset`
  * ``SA Cond - Normalize wForms.vi``                            -> :func:`normalize`
  * ``Conditionning - Truncate wForms.vi``                       -> :func:`truncate`
  * ``SA Math - ReSample ONE Signal.vi``                         -> :func:`resample`

The Scale Signals tab is a per-signal table of name, unit, calibration
factor and DC offset; :func:`calibrate` applies one row of it.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from ..model.signal import Signal

__all__ = [
    "NORMALIZATION_OPTIONS",
    "calibrate",
    "normalize",
    "offset",
    "resample",
    "scale",
    "truncate",
]

#: ``Normalization Option`` (``SA Cond - Normalize wForms.vi``)
NORMALIZATION_OPTIONS: tuple[str, ...] = (
    "None",
    "To itself",
    "To the max levels of ALL the signals",
)


def scale(signal: Signal, factor: float, *, annotate: bool = False) -> Signal:
    """Multiply by a calibration factor."""
    name = f"{signal.name} (x{factor:g})" if annotate else signal.name
    return signal.with_(name=name, y=signal.y * float(factor),
                        attributes={"Channel Name": name,
                                    "Scale_Factor": float(factor)})


def offset(signal: Signal, dc: float, *, annotate: bool = False) -> Signal:
    """Add a DC offset. Pass ``-signal.mean`` to remove the mean."""
    name = f"{signal.name} ({dc:+g})" if annotate else signal.name
    return signal.with_(name=name, y=signal.y + float(dc),
                        attributes={"Channel Name": name,
                                    "DC_Offset": float(dc)})


def calibrate(signal: Signal, *, factor: float = 1.0, dc: float = 0.0,
              name: str | None = None, unit: str | None = None) -> Signal:
    """Apply one row of the Scale Signals table.

    The order matters and follows the panel: the calibration factor scales
    the raw signal, then the DC offset is added in the calibrated units.
    """
    y = signal.y * float(factor) + float(dc)
    new_name = name if name is not None else signal.name
    new_unit = unit if unit is not None else signal.y_unit
    return signal.with_(
        name=new_name, y=y, y_unit=new_unit,
        attributes={"Channel Name": new_name, "Channel Unit": new_unit,
                    "Scale_Factor": float(factor), "DC_Offset": float(dc)},
    )


def normalize(signals: Sequence[Signal],
              option: str = NORMALIZATION_OPTIONS[1]
              ) -> tuple[list[Signal], float]:
    """Normalise a set of signals; returns ``(signals, max_of_all)``.

    * ``"To itself"`` divides each signal by its own peak, so every signal
      ends at +-1 and their relative levels are lost;
    * ``"To the max levels of ALL the signals"`` divides everything by the
      largest peak in the set, preserving relative levels.
    """
    if option not in NORMALIZATION_OPTIONS:
        raise ValueError(f"unknown normalization option {option!r}; "
                         f"expected one of {NORMALIZATION_OPTIONS}")
    signals = list(signals)
    peaks = [float(np.max(np.abs(s.y))) if s.n_samples else 0.0
             for s in signals]
    max_of_all = max(peaks) if peaks else 0.0

    if option == "None":
        return [s.with_() for s in signals], max_of_all

    out = []
    for sig, peak in zip(signals, peaks, strict=True):
        divisor = peak if option == "To itself" else max_of_all
        if divisor == 0.0:
            out.append(sig.with_())          # all-zero signal: leave it alone
            continue
        out.append(sig.with_(y=sig.y / divisor,
                             attributes={"Normalization": option}))
    return out, max_of_all


def truncate(signal: Signal, start: float, end: float) -> Signal:
    """Keep the samples between ``start`` and ``end`` seconds.

    Limits are given on the signal's own time axis (so they include
    ``t0``) and are clipped to the available range.
    """
    if end < start:
        start, end = end, start
    t = signal.t
    mask = (t >= start) & (t <= end)
    if not mask.any():
        raise ValueError(
            f"no samples between {start:g} and {end:g} s; the signal spans "
            f"{t[0]:g} to {t[-1]:g} s")
    first = int(np.argmax(mask))
    return signal.with_(y=signal.y[mask], t0=float(t[first]),
                        attributes={"Truncated_From": float(t[first]),
                                    "Truncated_To": float(t[mask][-1])})


def resample(signal: Signal, new_fs: float) -> Signal:
    """Resample to a new rate with an anti-aliased polyphase filter.

    Uses ``scipy.signal.resample_poly`` with the rational ratio closest to
    ``new_fs / fs``, so decimation is filtered rather than naive.
    """
    from fractions import Fraction

    from scipy.signal import resample_poly

    if new_fs <= 0:
        raise ValueError(f"new_fs must be positive, got {new_fs}")
    ratio = Fraction(new_fs / signal.fs).limit_denominator(1000)
    if ratio == 1:
        return signal.with_()
    y = resample_poly(signal.y, ratio.numerator, ratio.denominator)
    achieved = signal.fs * float(ratio)
    return signal.with_(
        y=y, dt=1.0 / achieved,
        attributes={"Resampled_From_Hz": signal.fs,
                    "Resampled_To_Hz": achieved},
    )
