"""Statistics and time-varying metrics.

The point of the LabVIEW fixtures here is the pair of *disagreeing*
normalisations SPWB inherits: NI's moments divide by N, NI's variance
divides by N-1, and Skewness/Kurtosis mix the two. Reproducing that faithfully
is what keeps trends computed here equal to trends computed in LabVIEW.
"""
import math
import pathlib

import numpy as np
import pytest

from spwb import Signal
from spwb.processing.dsp import metrics as M

FS = 1000.0
DT = 1.0 / FS
CASES = ["skewed", "tone", "gaussian", "tiny"]


@pytest.fixture(scope="session")
def lvm():
    path = (pathlib.Path(__file__).parent / "fixtures"
            / "labview_metrics_reference.npz")
    return np.load(path)


# -- the two NI conventions, pinned -----------------------------------------
@pytest.mark.parametrize("case", CASES)
def test_variance_uses_n_minus_one_like_labview(lvm, case):
    x = lvm[f"x_{case}"]
    assert np.var(x, ddof=1) == pytest.approx(float(lvm[f"var_{case}"]),
                                              rel=1e-12)
    # and is NOT the population variance
    assert np.var(x) != pytest.approx(float(lvm[f"var_{case}"]), rel=1e-6)


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("order", [2, 3, 4])
def test_moments_use_n_like_labview(lvm, case, order):
    x = lvm[f"x_{case}"]
    moment = np.mean((x - x.mean()) ** order)
    assert moment == pytest.approx(float(lvm[f"moment{order}_{case}"]),
                                   rel=1e-12)


@pytest.mark.parametrize("case", CASES)
def test_rms_matches_labview(lvm, case):
    x = lvm[f"x_{case}"]
    assert M.trend_value(x, "RMS") == pytest.approx(
        float(lvm[f"rms_{case}"]), rel=1e-12)


# -- the trend metrics themselves --------------------------------------------
@pytest.mark.parametrize("case", CASES)
def test_std_and_variance_trends_match_labview(lvm, case):
    x = lvm[f"x_{case}"]
    assert M.trend_value(x, "Variance") == pytest.approx(
        float(lvm[f"var_{case}"]), rel=1e-12)
    assert M.trend_value(x, "Standard Deviation") == pytest.approx(
        float(lvm[f"std_{case}"]), rel=1e-12)


@pytest.mark.parametrize("case", CASES)
def test_skewness_and_kurtosis_mix_the_two_conventions(lvm, case):
    """m/N over sigma from /(N-1) - exactly what the LabVIEW diagram wires."""
    x = lvm[f"x_{case}"]
    sigma = float(lvm[f"std_{case}"])
    expected_skew = float(lvm[f"moment3_{case}"]) / sigma ** 3
    expected_kurt = float(lvm[f"moment4_{case}"]) / sigma ** 4
    assert M.trend_value(x, "Skewness") == pytest.approx(expected_skew,
                                                         rel=1e-12)
    assert M.trend_value(x, "Kurtosis") == pytest.approx(expected_kurt,
                                                         rel=1e-12)


def test_kurtosis_is_not_excess_kurtosis(lvm):
    """A Gaussian reads ~3, not ~0: SPWB does not subtract 3."""
    value = M.trend_value(lvm["x_gaussian"], "Kurtosis")
    assert 2.7 < value < 3.3


def test_skewness_sign_follows_the_tail(lvm):
    assert M.trend_value(lvm["x_skewed"], "Skewness") > 0.5
    assert M.trend_value(-lvm["x_skewed"], "Skewness") < -0.5
    assert abs(M.trend_value(lvm["x_tone"], "Skewness")) < 1e-9


@pytest.mark.parametrize("trend, expected", [
    ("RMS", math.sqrt((1 + 4 + 9) / 3)),
    ("Absolute Peak", 3.0),
    ("Range", 5.0),
])
def test_simple_trends_are_what_they_say(trend, expected):
    x = np.array([-2.0, 1.0, 3.0])
    assert M.trend_value(x, trend) == pytest.approx(expected)


def test_unknown_trend_rejected():
    with pytest.raises(ValueError, match="trend type"):
        M.trend_value(np.zeros(10), "Median")


@pytest.mark.parametrize("trend", ["Standard Deviation", "Variance",
                                   "Skewness", "Kurtosis"])
def test_degenerate_blocks_give_nan_not_a_crash(trend):
    assert math.isnan(M.trend_value(np.array([1.0]), trend))     # N < 2
    if trend in ("Skewness", "Kurtosis"):
        assert math.isnan(M.trend_value(np.ones(50), trend))     # sigma == 0


# -- the sliding window ------------------------------------------------------
@pytest.fixture
def burst():
    """Quiet, then loud, then quiet - so an RMS trend has an obvious shape."""
    n = 10_000
    y = 0.1 * np.ones(n)
    y[4000:6000] = 2.0
    return Signal("burst", y, DT, y_unit="Pa")


def test_window_arithmetic_follows_the_panel(burst):
    out = M.time_varying_metric(burst, "RMS", step_ms=100.0, length_ms=500.0)
    assert out.attributes["TVM_Step_Samples"] == 100      # 100 ms at 1 kHz
    assert out.attributes["TVM_Window_Samples"] == 500
    assert out.n_samples == (10_000 - 500) // 100 + 1
    assert out.dt == pytest.approx(0.1)                   # sampled at the step


def test_trend_tracks_the_burst(burst):
    out = M.time_varying_metric(burst, "RMS", step_ms=100.0, length_ms=200.0)
    quiet = out.y[out.t < 3.5]
    loud = out.y[(out.t > 4.3) & (out.t < 5.7)]
    assert np.allclose(quiet, 0.1, atol=1e-9)
    assert np.allclose(loud, 2.0, atol=1e-9)


def test_points_sit_at_window_centres(burst):
    """Otherwise the trend appears shifted by half a window against the data."""
    out = M.time_varying_metric(burst, "RMS", step_ms=100.0, length_ms=500.0)
    assert out.t0 == pytest.approx((500 - 1) / 2 * DT)
    rising = out.t[int(np.argmax(out.y > 0.5))]
    assert 3.7 < rising < 4.3          # the burst starts at 4.0 s


def test_every_trend_type_runs(burst):
    for trend in M.TREND_TYPES:
        out = M.time_varying_metric(burst, trend, step_ms=200.0,
                                    length_ms=1000.0)
        assert out.n_samples > 1
        assert out.attributes["TVM_Trend_Type"] == trend


def test_units_follow_the_metric(burst):
    assert M.time_varying_metric(burst, "RMS", step_ms=100,
                                 length_ms=500).y_unit == "Pa"
    assert M.time_varying_metric(burst, "Variance", step_ms=100,
                                 length_ms=500).y_unit == "Pa²"
    assert M.time_varying_metric(burst, "Kurtosis", step_ms=100,
                                 length_ms=500).y_unit == ""


def test_annotate_marks_the_name(burst):
    out = M.time_varying_metric(burst, "RMS", step_ms=100.0, length_ms=500.0,
                                annotate=True)
    assert out.name == "burst (TVM)"
    assert out.attributes["Channel Name"] == "burst (TVM)"


@pytest.mark.parametrize("kwargs, message", [
    (dict(step_ms=0), "positive"),
    (dict(length_ms=-1), "positive"),
    (dict(length_ms=1e9), "signal has"),
])
def test_invalid_windows_rejected(burst, kwargs, message):
    params = dict(step_ms=100.0, length_ms=500.0)
    params.update(kwargs)
    with pytest.raises(ValueError, match=message):
        M.time_varying_metric(burst, "RMS", **params)


# -- basic statistics --------------------------------------------------------
def test_statistics_of_a_known_signal():
    t = np.arange(2000) * DT
    sig = Signal("sine", 3.0 * np.sin(2 * np.pi * 10 * t) + 1.0, DT,
                 y_unit="V")
    s = M.signal_statistics(sig)
    assert s.name == "sine" and s.unit == "V"
    assert s.maximum == pytest.approx(4.0, abs=1e-3)
    assert s.minimum == pytest.approx(-2.0, abs=1e-3)
    assert s.mean == pytest.approx(1.0, abs=1e-3)
    assert s.rms == pytest.approx(math.sqrt(1.0 + 9.0 / 2), rel=1e-3)
    assert s.n_samples == 2000
    assert s.duration_ms == pytest.approx(2000.0)
    assert s.peak_to_peak == pytest.approx(6.0, abs=1e-3)
    assert s.crest_factor == pytest.approx(4.0 / s.rms, rel=1e-6)


def test_statistics_of_a_constant_signal():
    s = M.signal_statistics(Signal("dc", np.full(100, 2.5), DT))
    assert s.minimum == s.maximum == s.mean == pytest.approx(2.5)
    assert s.rms == pytest.approx(2.5)
    assert s.peak_to_peak == 0.0
    assert s.crest_factor == pytest.approx(1.0)
