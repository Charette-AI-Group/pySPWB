"""LMS adaptive noise cancellation.

There is no LabVIEW fixture here: SPWB's LMS wraps NI's Adaptive Filter
Toolkit, whose filter object is a refnum that does not cross COM. The
tests instead pin the behaviour that makes an adaptive filter correct -
it must actually recover a known signal buried in noise, and it must not
be able to do so when the reference carries no information about that
noise.
"""
import numpy as np
import pytest

from spwb import Signal
from spwb.processing.dsp import adaptive as A

FS = 2000.0
DT = 1.0 / FS
N = 8000


def scenario(seed=0, delay=5, gain=0.8, speech_amp=1.0, noise_amp=1.0):
    """Classic noise cancellation: d = speech + path(noise), x = noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(N) * DT
    speech = speech_amp * np.sin(2 * np.pi * 60 * t)
    noise = noise_amp * rng.standard_normal(N)
    contamination = gain * np.roll(noise, delay)
    contamination[:delay] = 0.0
    reference = Signal("noise ref", noise, DT, y_unit="V")
    noisy = Signal("mic", speech + contamination, DT, y_unit="Pa")
    return reference, noisy, speech


# -- it must actually work ---------------------------------------------------
@pytest.mark.parametrize("filter_class, step", [
    # Plain LMS is stable only below 2/(taps * reference power) - about
    # 0.007 here - so it needs a far smaller step than the panel's
    # documented 0..2 range suggests. NLMS rescales by that power and so
    # takes the documented range directly.
    ("LMS", 0.001),
    ("Normalized LMS", 0.5),
])
def test_recovers_a_signal_buried_in_correlated_noise(filter_class, step):
    reference, noisy, speech = scenario(noise_amp=3.0)
    result = A.lms_filter(reference, noisy, filter_length=32,
                          step_size=step, filter_class=filter_class)

    # compare over the second half, after the filter has adapted
    half = N // 2
    error_before = np.sqrt(np.mean((noisy.y[half:] - speech[half:]) ** 2))
    error_after = np.sqrt(np.mean((result.filtered.y[half:] - speech[half:])
                                  ** 2))
    assert error_after < error_before / 5
    assert result.noise_reduction_db > 6.0


def test_converges_by_the_cross_correlation_metric():
    reference, noisy, _ = scenario(noise_amp=3.0)
    result = A.lms_filter(reference, noisy, filter_length=32, step_size=0.5,
                          filter_class="Normalized LMS")
    assert result.convergence[0] > result.convergence[-1]
    assert result.converged
    assert len(result.block_times) == len(result.convergence)


def test_learns_the_actual_path():
    """A pure delay-and-gain path must show up in the coefficients."""
    reference, noisy, _ = scenario(delay=5, gain=0.8, speech_amp=0.0,
                                   noise_amp=1.0)
    result = A.lms_filter(reference, noisy, filter_length=32, step_size=0.5,
                          filter_class="Normalized LMS")
    peak_tap = int(np.argmax(np.abs(result.coefficients)))
    assert peak_tap == 5
    assert result.coefficients[peak_tap] == pytest.approx(0.8, abs=0.05)


def test_an_uncorrelated_reference_removes_nothing():
    """The honest negative: no information, no cancellation.

    Compared against the correlated case rather than an absolute level -
    an adaptive filter always fits a little of the noise by chance
    (misadjustment), and the meaningful claim is that it fits far less.
    """
    rng = np.random.default_rng(1)
    t = np.arange(N) * DT
    speech = np.sin(2 * np.pi * 60 * t)
    noise = rng.standard_normal(N)
    contamination = 0.8 * np.roll(noise, 5)
    noisy = Signal("mic", speech + contamination, DT)

    # the panel's default step; a larger one trades steady-state accuracy
    # for convergence speed and narrows the gap measured below
    useful = A.lms_filter(Signal("ref", noise, DT), noisy, filter_length=32,
                          step_size=0.1, filter_class="Normalized LMS")
    useless = A.lms_filter(Signal("unrelated", rng.standard_normal(N), DT),
                           noisy, filter_length=32, step_size=0.1,
                           filter_class="Normalized LMS")

    # here the speech is as loud as the noise, so the *total* level cannot
    # drop far even on a perfect cancellation; the comparison is the point
    assert useful.noise_reduction_db > 2.0
    # A useless reference does not merely fail to help - it makes things
    # slightly worse, because the filter keeps subtracting an estimate that
    # is uncorrelated with anything (misadjustment). Worth knowing: if the
    # level goes UP, the reference is not carrying the contamination.
    assert useless.noise_reduction_db < 0.0

    # what matters: the useful run recovers the speech, the other does not.
    # (The *size* of what each filter subtracts is not a discriminator - the
    #  useless one subtracts just as much, it is simply the wrong thing.)
    half = N // 2
    assert (np.sqrt(np.mean((useful.filtered.y[half:] - speech[half:]) ** 2))
            < np.sqrt(np.mean((useless.filtered.y[half:] - speech[half:])
                              ** 2)) / 3)


def test_the_removed_and_filtered_parts_add_back_to_the_input():
    reference, noisy, _ = scenario()
    result = A.lms_filter(reference, noisy, filter_length=16, step_size=0.1)
    np.testing.assert_allclose(result.filtered.y + result.removed.y, noisy.y,
                               atol=1e-9)


def test_a_longer_filter_spans_a_longer_delay():
    """Too few taps cannot represent the path, so cancellation fails."""
    reference, noisy, _ = scenario(delay=40, gain=0.9, speech_amp=0.0)
    short = A.lms_filter(reference, noisy, filter_length=8, step_size=0.5,
                         filter_class="Normalized LMS")
    long = A.lms_filter(reference, noisy, filter_length=64, step_size=0.5,
                        filter_class="Normalized LMS")
    assert long.noise_reduction_db > short.noise_reduction_db + 10


def test_normalized_lms_tolerates_a_loud_reference():
    """Plain LMS diverges when the reference is large; NLMS should not."""
    reference, noisy, _ = scenario(noise_amp=50.0, speech_amp=1.0)
    nlms = A.lms_filter(reference, noisy, filter_length=32, step_size=0.5,
                        filter_class="Normalized LMS")
    assert np.isfinite(nlms.filtered.y).all()
    assert nlms.noise_reduction_db > 6.0


def test_leakage_keeps_coefficients_bounded():
    reference, noisy, _ = scenario()
    leaky = A.lms_filter(reference, noisy, filter_length=32, step_size=0.5,
                         filter_class="Normalized LMS", leakage=1e-4)
    plain = A.lms_filter(reference, noisy, filter_length=32, step_size=0.5,
                         filter_class="Normalized LMS")
    assert np.isfinite(leaky.coefficients).all()
    assert leaky.metadata["LMS_Leakage"] == 1e-4
    # leakage pulls taps toward zero, so the filter is never larger for it
    assert np.linalg.norm(leaky.coefficients) <= \
        np.linalg.norm(plain.coefficients) * 1.05


# -- the metric --------------------------------------------------------------
def test_cross_correlation_metric_bounds():
    rng = np.random.default_rng(2)
    a = rng.standard_normal(500)
    assert A.cross_correlation_metric(a, a) == pytest.approx(1.0, rel=1e-9)
    assert A.cross_correlation_metric(a, -a) == pytest.approx(1.0, rel=1e-9)
    assert A.cross_correlation_metric(a, rng.standard_normal(500)) < 0.3


def test_cross_correlation_metric_degenerate_inputs():
    assert A.cross_correlation_metric(np.array([]), np.array([])) == 0.0
    assert A.cross_correlation_metric(np.zeros(10), np.ones(10)) == 0.0


def test_threshold_matches_the_labview_accept_band():
    assert A.convergence_threshold == 0.01


def test_convergence_bar_accounts_for_the_block_length():
    """A fixed 0.01 is unreachable on short blocks: two unrelated 250-sample
    blocks already score around 0.1 by chance, so the bar must adapt."""
    reference, noisy, _ = scenario(noise_amp=3.0)
    result = A.lms_filter(reference, noisy, filter_length=32, step_size=0.5,
                          filter_class="Normalized LMS", blocks=32)
    assert result.noise_floor > A.convergence_threshold
    assert result.converged                      # it did all it could

    # more samples per block resolve a smaller correlation
    coarse = A.lms_filter(reference, noisy, filter_length=32, step_size=0.5,
                          filter_class="Normalized LMS", blocks=4)
    assert coarse.noise_floor < result.noise_floor


def test_diverging_settings_are_reported_not_returned_as_inf():
    """Plain LMS above its stability bound must raise, not hand back inf."""
    reference, noisy, _ = scenario(noise_amp=3.0)
    with pytest.raises(ValueError, match="diverged"):
        A.lms_filter(reference, noisy, filter_length=32, step_size=0.5,
                     filter_class="LMS")


def test_the_divergence_message_suggests_a_usable_step():
    reference, noisy, _ = scenario(noise_amp=3.0)
    try:
        A.lms_filter(reference, noisy, filter_length=32, step_size=0.5,
                     filter_class="LMS")
    except ValueError as exc:
        assert "Normalized LMS" in str(exc)
        assert "stable only for a step below" in str(exc)


def test_max_lag_restricts_the_search():
    rng = np.random.default_rng(5)
    x = rng.standard_normal(2000)
    delayed = np.roll(x, 100)
    assert A.cross_correlation_metric(delayed, x) > 0.9        # finds lag 100
    assert A.cross_correlation_metric(delayed, x, max_lag=10) < 0.3


# -- provenance and validation -----------------------------------------------
def test_outputs_are_named_and_carry_settings():
    reference, noisy, _ = scenario()
    result = A.lms_filter(reference, noisy, filter_length=16, step_size=0.25,
                          filter_class="Noise Cancelling (BGN Ref)")
    assert result.filtered.name == "mic (LMS)"
    assert result.removed.name == "mic (removed)"
    assert result.filtered.y_unit == "Pa"
    assert result.filtered.attributes["LMS_Step_Size"] == 0.25
    assert result.filtered.attributes["LMS_Filter_Length"] == 16
    assert result.filtered.attributes["LMS_Reference"] == "noise ref"
    assert result.filtered.attributes["LMS_Filter_Class"] == \
        "Noise Cancelling (BGN Ref)"
    # independent of the input, so the store gets distinct signals
    assert result.filtered.sid != noisy.sid
    assert result.removed.sid != result.filtered.sid


@pytest.mark.parametrize("kwargs, message", [
    (dict(step_size=0), "step size"),
    (dict(step_size=2), "step size"),
    (dict(step_size=-0.5), "step size"),
    (dict(filter_length=0), "filter_length"),
    (dict(filter_class="Kalman"), "filter class"),
    (dict(filter_length=100_000), "exceeds"),
])
def test_invalid_parameters_rejected(kwargs, message):
    reference, noisy, _ = scenario()
    params = dict(filter_length=16, step_size=0.1)
    params.update(kwargs)
    with pytest.raises(ValueError, match=message):
        A.lms_filter(reference, noisy, **params)


def test_mismatched_inputs_rejected():
    reference, noisy, _ = scenario()
    with pytest.raises(ValueError, match="same length"):
        A.lms_filter(reference, noisy.with_(y=noisy.y[:100]),
                     filter_length=16)
    with pytest.raises(ValueError, match="sample rate"):
        A.lms_filter(reference, noisy.with_(dt=DT * 2), filter_length=16)


def test_every_filter_class_runs():
    reference, noisy, _ = scenario()
    for filter_class in A.LMS_FILTER_CLASSES:
        step = 0.01 if filter_class == "LMS" else 0.5
        result = A.lms_filter(reference, noisy, filter_length=16,
                              step_size=step, filter_class=filter_class)
        assert np.isfinite(result.filtered.y).all()
        assert result.filter_class == filter_class
