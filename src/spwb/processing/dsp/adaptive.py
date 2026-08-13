"""Adaptive filtering - port of SPWB's AdvSigProc LMS.

Ported from (LabVIEW block diagrams in SPWB_export):
  * ``Initialize LMS Filter.vi`` / ``Apply LMS Filter.vi``
    -> :func:`lms_filter`
  * ``Iteration Metric - X Correlation.vi``
    -> :func:`cross_correlation_metric`
  * ``LMS Adaptive Filtering (V1.00).vi``   -> the window's controls
  * ``LMS Input Parameters.ctl``            -> :data:`LMS_FILTER_CLASSES`

**What this is for.** Adaptive noise cancellation. You have a *noisy*
signal ``d = s + n`` (what you want, plus contamination) and a *reference*
``x`` that is correlated with ``n`` but not with ``s`` - a second
microphone near the noise source, a tacho, an accelerometer on the
offending machine. The filter learns, sample by sample, how ``x`` maps into
``n``, subtracts its estimate, and what is left is ``s``.

The output you usually want is therefore the **error** signal, not the
filter's own output: ``e = d - y`` is the cleaned result, and ``y`` is the
contamination that was removed.

Convergence is judged the way the original does it - by cross-correlation.
``Iteration Metric - X Correlation.vi`` carries the comment *"The
X-Correlation between the LMS Filtered speech and LMS Filtered BGN should
be 0 !!"*, with an accept band of 0 to 0.01. When the residual still
correlates with the reference, there is contamination left to remove.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

from ..model.signal import Signal

__all__ = [
    "LMS_FILTER_CLASSES",
    "LMSResult",
    "convergence_threshold",
    "cross_correlation_metric",
    "lms_filter",
]

#: ``Filter Class`` on the LMS panel (``LMS Input Parameters.ctl``).
#:
#: ``LMS`` and ``Normalized LMS`` are the two algorithms. The two
#: "Noise Cancelling" entries are presets of the normalised algorithm, named
#: for which signal is wired to the reference input: with a background-noise
#: reference the filter removes that noise, with a speech reference it
#: removes the speech. The maths is the same; only the roles differ.
LMS_FILTER_CLASSES: tuple[str, ...] = (
    "LMS",
    "Normalized LMS",
    "Noise Cancelling (BGN Ref)",
    "Noise Cancelling (Speech Ref)",
)

_NORMALISED = {"Normalized LMS", "Noise Cancelling (BGN Ref)",
               "Noise Cancelling (Speech Ref)"}

#: the accept band from ``Iteration Metric - X Correlation.vi``
convergence_threshold: float = 0.01


@dataclass
class LMSResult:
    """What one adaptive run produced."""

    filtered: Signal            # e = d - y, the cleaned signal
    removed: Signal             # y, the contamination the filter identified
    coefficients: np.ndarray    # the final filter, newest tap first
    convergence: np.ndarray     # |cross-correlation| per block, over time
    block_times: np.ndarray     # seconds, one per convergence point
    filter_class: str = "LMS"
    step_size: float = 0.1
    noise_floor: float = 0.0    # chance-level correlation for these blocks
    metadata: dict = field(default_factory=dict)

    @property
    def converged(self) -> bool:
        """True when the residual no longer tracks the reference.

        The bar is LabVIEW's 0.01 band *or* the chance level for the block
        length, whichever is larger. Short blocks cannot resolve a
        correlation of 0.01 - two unrelated blocks of 250 samples already
        score about 0.1 - so comparing against the fixed band alone would
        report "not converged" for a filter that has done all it can.
        """
        if not self.convergence.size:
            return False
        bar = max(convergence_threshold, self.noise_floor)
        return bool(self.convergence[-1] <= bar)

    @property
    def noise_reduction_db(self) -> float:
        """Drop in overall level, in dB.

        This is the *total* reduction, so it is bounded by how much of the
        input was contamination: cancelling noise perfectly out of a signal
        that is half noise gives about 3 dB, not infinity.

        A **negative** value is meaningful - it says the reference did not
        carry the contamination, so the filter only added its own
        misadjustment noise. Check the reference before touching the step
        size.
        """
        before = float(np.sqrt(np.mean(
            (self.filtered.y + self.removed.y) ** 2)))
        after = float(np.sqrt(np.mean(self.filtered.y ** 2)))
        if before <= 0 or after <= 0:
            return 0.0
        return 20.0 * np.log10(before / after)


def cross_correlation_metric(a: np.ndarray, b: np.ndarray, *,
                             max_lag: int | None = None) -> float:
    """Peak |normalised cross-correlation| between two signals, in [0, 1].

    ``Iteration Metric - X Correlation.vi``: 0 means the two share nothing,
    so an adaptive filter whose residual scores 0 against its reference has
    removed everything the reference could explain.

    ``max_lag`` restricts the search to +-that many samples. For judging an
    adaptive filter, the lags worth looking at are the ones the filter can
    actually model - correlation beyond its reach is not something more
    adaptation could remove.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size == 0 or b.size == 0:
        return 0.0
    a = a - a.mean()
    b = b - b.mean()
    denominator = np.sqrt(np.sum(a * a) * np.sum(b * b))
    if denominator <= 0:
        return 0.0
    correlation = np.correlate(a, b, mode="full")
    if max_lag is not None:
        centre = len(b) - 1
        lo = max(0, centre - int(max_lag))
        hi = min(len(correlation), centre + int(max_lag) + 1)
        correlation = correlation[lo:hi]
    return float(np.max(np.abs(correlation)) / denominator)


def _chance_correlation(n_samples: int, n_lags: int) -> float:
    """Roughly the largest |correlation| two unrelated blocks will show.

    Each lag's correlation has a standard error near ``1/sqrt(n)``, and
    taking the maximum over several lags inflates that. Without this floor,
    a convergence test against a fixed threshold is unreachable for short
    blocks: the metric bottoms out at chance, not at zero.
    """
    if n_samples <= 1:
        return 1.0
    spread = 1.0 / np.sqrt(n_samples)
    return float(min(1.0, spread * (2.0 + 0.6 * np.log(max(n_lags, 1)))))


def lms_filter(reference: Signal, noisy: Signal, *,
               filter_length: int = 32,
               step_size: float = 0.1,
               filter_class: str = "LMS",
               leakage: float = 0.0,
               blocks: int = 32) -> LMSResult:
    """Adaptively remove from ``noisy`` whatever ``reference`` can explain.

    Parameters
    ----------
    reference:
        The signal correlated with the contamination (``x``).
    noisy:
        The signal to clean (``d``).
    filter_length:
        Number of FIR taps. It must span the delay/reverberation between
        the reference and the contamination, or the filter cannot represent
        the path.
    step_size:
        Adaptation rate ``mu``. The panel documents the stable range as
        ``0 < mu < 2``; larger converges faster but leaves more steady-state
        error, and too large diverges.
    leakage:
        Optional leaky-LMS coefficient decay per sample, which keeps taps
        from drifting when the reference goes quiet. 0 disables it.
    blocks:
        How many points to report on the convergence trace.

    Returns
    -------
    LMSResult
        ``filtered`` is the cleaned signal (the error ``e``), ``removed`` is
        what was taken out (``y``).
    """
    if filter_class not in LMS_FILTER_CLASSES:
        raise ValueError(f"unknown filter class {filter_class!r}; "
                         f"expected one of {LMS_FILTER_CLASSES}")
    if not 0 < step_size < 2:
        raise ValueError(
            f"step size must be greater than 0 and less than 2, got "
            f"{step_size}; the filter is unstable outside that range")
    filter_length = int(filter_length)
    if filter_length < 1:
        raise ValueError(f"filter_length must be >= 1, got {filter_length}")
    if reference.n_samples != noisy.n_samples:
        raise ValueError(
            f"reference and noisy signals must be the same length, got "
            f"{reference.n_samples} and {noisy.n_samples} samples")
    if not np.isclose(reference.dt, noisy.dt, rtol=1e-12):
        raise ValueError(
            f"reference and noisy signals must share a sample rate, got "
            f"{reference.fs:g} Hz and {noisy.fs:g} Hz")
    if filter_length > reference.n_samples:
        raise ValueError(
            f"filter_length {filter_length} exceeds the signal length "
            f"({reference.n_samples} samples)")

    x = np.asarray(reference.y, dtype=float)
    d = np.asarray(noisy.y, dtype=float)
    n_samples = len(x)
    normalised = filter_class in _NORMALISED

    w = np.zeros(filter_length)
    y = np.empty(n_samples)
    e = np.empty(n_samples)
    # a sliding view of the most recent taps, newest first
    window = np.zeros(filter_length)
    epsilon = 1e-12
    decay = 1.0 - leakage

    # A diverging filter overflows on its way to inf. That is a real
    # outcome, reported below with a message that says what to change, so
    # the warnings on the way there are just noise.
    with np.errstate(over="ignore", invalid="ignore"):
        for n in range(n_samples):
            window[1:] = window[:-1]
            window[0] = x[n]
            estimate = float(w @ window)
            error = d[n] - estimate
            y[n] = estimate
            e[n] = error
            if normalised:
                gain = step_size / (epsilon + float(window @ window))
            else:
                gain = step_size
            if leakage:
                w *= decay
            w += gain * error * window

    if not np.all(np.isfinite(w)) or not np.all(np.isfinite(e)):
        # Plain LMS is only stable for mu < 2 / (taps * mean square of the
        # reference), so the panel's documented "0 < step size < 2" - which
        # is the *normalised* bound - can still diverge here. Say so, rather
        # than handing back an array of inf.
        power = float(np.mean(x * x))
        suggestion = (2.0 / (filter_length * power)) if power > 0 else 2.0
        raise ValueError(
            f"the filter diverged with {filter_class!r} at step size "
            f"{step_size:g}. Plain LMS is stable only for a step below "
            f"about {suggestion:.3g} with this reference "
            f"({filter_length} taps, mean square {power:.4g}). Reduce the "
            f"step size, or use 'Normalized LMS', which rescales by the "
            f"reference power and takes the documented 0 to 2 range.")

    # convergence trace: how much of the reference still shows in the residual
    n_blocks = max(1, min(int(blocks), n_samples // max(filter_length, 8)))
    edges = np.linspace(0, n_samples, n_blocks + 1).astype(int)
    spans = [(lo, hi) for lo, hi in itertools.pairwise(edges) if hi > lo]
    # only the lags the filter can model: correlation further out is not
    # something more adaptation could have removed
    convergence = np.array([
        cross_correlation_metric(e[lo:hi], x[lo:hi], max_lag=filter_length)
        for lo, hi in spans
    ])
    block_times = np.array([noisy.t0 + (lo + hi) / 2.0 * noisy.dt
                            for lo, hi in spans])
    block_samples = min(hi - lo for lo, hi in spans)
    noise_floor = _chance_correlation(block_samples, 2 * filter_length + 1)

    common = {
        "LMS_Filter_Class": filter_class,
        "LMS_Step_Size": float(step_size),
        "LMS_Filter_Length": filter_length,
        "LMS_Reference": reference.name,
        "LMS_Leakage": float(leakage),
    }
    filtered = noisy.copy(
        name=f"{noisy.name} (LMS)", y=e,
        attributes={**common, "Channel Name": f"{noisy.name} (LMS)"})
    removed = noisy.copy(
        name=f"{noisy.name} (removed)", y=y,
        attributes={**common, "Channel Name": f"{noisy.name} (removed)"})

    return LMSResult(
        filtered=filtered,
        removed=removed,
        coefficients=w.copy(),
        convergence=convergence,
        block_times=block_times,
        filter_class=filter_class,
        step_size=float(step_size),
        noise_floor=noise_floor,
        metadata=common,
    )
