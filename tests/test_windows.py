"""Windows vs LabVIEW 2022 ground truth.

Two fixture files:
  * labview_raw_windows.npz  - the unscaled windows w[n] recovered from NI's
    Scaled Time Domain Window (x = ones), plus NI's reported ENBW/CG.
  * labview_reference.npz    - windowed sine + full APS chain (test_spectral).

Note on props tolerance: NI returns *tabulated* ENBW constants for the fixed
windows (e.g. Hamming 1.362826 where the exact value is 1.3628258...), while
spwb computes them from the samples. rel=3e-6 covers NI's table rounding;
parametrized windows (kaiser/chebyshev/gaussian) are computed by NI too and
match far tighter.
"""
import math
import pathlib

import numpy as np
import pytest

from spwb.processing.dsp import windows as W

FIXTURE_WINDOWS = {
    "rectangular": math.nan, "hanning": math.nan, "hamming": math.nan,
    "blackman_harris": math.nan, "exact_blackman": math.nan,
    "blackman": math.nan, "flat_top": math.nan, "bh_4term": math.nan,
    "bh_7term": math.nan, "low_sidelobe": math.nan,
    "blackman_nuttall": math.nan, "triangle": math.nan,
    "bartlett_hanning": math.nan, "bohman": math.nan, "parzen": math.nan,
    "welch": math.nan, "kaiser": 8.0, "dolph_chebyshev": 60.0,
    "gaussian": 0.2,
}


@pytest.fixture(scope="session")
def lvraw():
    path = pathlib.Path(__file__).parent / "fixtures" / "labview_raw_windows.npz"
    return np.load(path)


@pytest.mark.parametrize("name", FIXTURE_WINDOWS)
def test_window_shape_matches_labview(lvraw, name):
    w = W.window(name, 1024, FIXTURE_WINDOWS[name])
    np.testing.assert_allclose(w, lvraw[f"raww_{name}"], rtol=1e-7, atol=1e-8,
                               err_msg=f"window shape mismatch: {name}")


@pytest.mark.parametrize("name", FIXTURE_WINDOWS)
def test_window_props_match_labview(lvraw, name):
    p = W.props(W.window(name, 1024, FIXTURE_WINDOWS[name]))
    ref_enbw, ref_cg = lvraw[f"rawprops_{name}"]
    assert p.eq_noise_bw == pytest.approx(ref_enbw, rel=3e-6), name
    assert p.coherent_gain == pytest.approx(ref_cg, rel=3e-6), name


@pytest.mark.parametrize("name", FIXTURE_WINDOWS)
def test_scaled_window_matches_labview(lv, name):
    """Full scaled-window output on a real signal (amplitude-preserving)."""
    x = lv["sig_sine_offbin"]
    wx, _ = W.scaled_window(x, name, FIXTURE_WINDOWS[name])
    ref = lv[f"win_{name}_wx"]
    np.testing.assert_allclose(wx, ref, rtol=1e-6, atol=1e-9,
                               err_msg=f"scaled window mismatch: {name}")


def test_all_menu_windows_exist():
    for name in W.WINDOW_NAMES:
        w = W.window(name, 256)
        assert len(w) == 256 and np.isfinite(w).all(), name
