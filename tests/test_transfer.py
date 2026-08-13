"""Transfer functions and coherence.

Three layers of checking:
  * the cross spectrum against LabVIEW 2022 fixtures (bit-level convention);
  * the estimators against analytically-known systems (gain, delay, filter);
  * the statistical behaviour that makes H1/coherence worth having at all
    (noise rejection, coherence dropping where noise dominates).
"""
import pathlib

import numpy as np
import pytest

from spwb import Signal
from spwb.processing.dsp import transfer as T

FS = 1024.0
DT = 1.0 / FS


@pytest.fixture(scope="session")
def lvtf():
    path = pathlib.Path(__file__).parent / "fixtures" / "labview_tf_reference.npz"
    return np.load(path)


def sig(y, name="s", unit=""):
    return Signal(name, y, DT, y_unit=unit)


# -- cross spectrum vs LabVIEW ----------------------------------------------
@pytest.mark.parametrize("case", ["noise_pair", "sine_pair", "mixed"])
def test_cross_power_spectrum_matches_labview(lvtf, case):
    x, y = lvtf[f"x_{case}"], lvtf[f"y_{case}"]
    sxy, df = T.cross_power_spectrum(x, y, DT)
    reference = lvtf[f"cps_mag_{case}"] * np.exp(1j * lvtf[f"cps_phase_{case}"])
    assert len(sxy) == len(reference)
    assert df == pytest.approx(float(lvtf["df"]))
    np.testing.assert_allclose(sxy, reference, rtol=1e-9, atol=1e-14)


def test_cross_spectrum_dc_and_nyquist_are_not_doubled(lvtf):
    """The single-sided doubling skips the bins with no mirror image."""
    x, y = lvtf["x_mixed"], lvtf["y_mixed"]
    n = len(x)
    sxy, _ = T.cross_power_spectrum(x, y, DT)
    raw = np.conj(np.fft.rfft(x)) * np.fft.rfft(y) / (n * n)
    assert sxy[0] == pytest.approx(raw[0])
    assert sxy[-1] == pytest.approx(raw[-1])
    assert sxy[1] == pytest.approx(2 * raw[1])


def test_cross_spectrum_of_a_signal_with_itself_is_its_auto_spectrum(lvtf):
    x = lvtf["x_noise_pair"]
    sxx, _ = T.cross_power_spectrum(x, x, DT)
    from spwb.processing.dsp import auto_power_spectrum
    aps, _ = auto_power_spectrum(x, DT)
    assert np.allclose(sxx.imag, 0.0, atol=1e-18)
    np.testing.assert_allclose(sxx.real[:len(aps)], aps, rtol=1e-9)


def test_length_mismatch_is_rejected():
    with pytest.raises(ValueError, match="same length"):
        T.cross_power_spectrum(np.zeros(8), np.zeros(9), DT)


# -- estimators on known systems --------------------------------------------
def test_pure_gain_is_recovered_flat():
    rng = np.random.default_rng(1)
    x = rng.standard_normal(8192)
    tf, coh = T.transfer_function(sig(x, "ref"), sig(2.5 * x, "resp"),
                                  freq_resolution=4.0)
    mid = slice(5, -5)                       # ignore edge bins
    np.testing.assert_allclose(tf.y[mid], 2.5, rtol=1e-6)
    np.testing.assert_allclose(coh.y[mid], 1.0, rtol=1e-9)


def test_pure_delay_gives_linear_phase():
    """A d-sample delay is phase = -2*pi*f*d*dt, i.e. a straight line."""
    rng = np.random.default_rng(2)
    x = rng.standard_normal(8192)
    delay = 4
    y = np.roll(x, delay)
    tf, _ = T.transfer_function(sig(x, "ref"), sig(y, "resp"),
                                freq_resolution=4.0, window="rectangular")
    unwrapped = T.format_transfer_function(tf, "Phase Unwrap (Rad)")
    freqs = tf.t[5:-5]
    expected = -2 * np.pi * freqs * delay * DT
    # compare slopes: both are linear in f
    got_slope = np.polyfit(freqs, unwrapped.y[5:-5], 1)[0]
    want_slope = np.polyfit(freqs, expected, 1)[0]
    assert got_slope == pytest.approx(want_slope, rel=1e-3)


def test_known_filter_response_is_recovered():
    """A 1-pole IIR: H(f) = b / (1 - a e^{-j2 pi f dt}) - checked per bin."""
    from scipy.signal import freqz, lfilter
    rng = np.random.default_rng(3)
    x = rng.standard_normal(1 << 15)
    b, a = [0.3], [1.0, -0.7]
    y = lfilter(b, a, x)
    tf, coh = T.transfer_function(sig(x, "ref"), sig(y, "resp"),
                                  freq_resolution=2.0, window="hanning")
    h = np.asarray(tf.attributes["TF_Complex"])
    _, expected = freqz(b, a, worN=tf.t * 2 * np.pi * DT)
    mid = slice(10, -10)
    np.testing.assert_allclose(np.abs(h[mid]), np.abs(expected[mid]), rtol=0.02)
    # not exactly 1: the filter's memory crosses block boundaries, so each
    # block's output depends on samples the block does not contain
    assert coh.y[mid].min() > 0.999


# -- why H1 and coherence exist ----------------------------------------------
def test_h1_rejects_noise_on_the_response():
    """The estimator's whole point: output noise averages out of Sxy."""
    rng = np.random.default_rng(4)
    n = 1 << 16
    x = rng.standard_normal(n)
    clean = 2.0 * x
    noisy = clean + 2.0 * rng.standard_normal(n)     # SNR ~ 0 dB
    tf, coh = T.transfer_function(sig(x, "ref"), sig(noisy, "resp"),
                                  freq_resolution=8.0, overlap=0.5)
    mid = slice(5, -5)
    assert np.abs(np.median(tf.y[mid]) - 2.0) < 0.05   # gain still recovered
    assert 0.4 < np.median(coh.y[mid]) < 0.6           # but coherence says ~0.5


def test_coherence_is_low_for_unrelated_signals():
    rng = np.random.default_rng(5)
    a = rng.standard_normal(1 << 15)
    b = rng.standard_normal(1 << 15)
    _, coh = T.transfer_function(sig(a, "a"), sig(b, "b"),
                                 freq_resolution=8.0, overlap=0.5)
    assert np.median(coh.y) < 0.2


def test_coherence_is_bounded_to_unit_interval():
    rng = np.random.default_rng(6)
    x = rng.standard_normal(4096)
    _, coh = T.transfer_function(sig(x, "a"),
                                 sig(rng.standard_normal(4096), "b"),
                                 freq_resolution=8.0)
    assert coh.y.min() >= 0.0 and coh.y.max() <= 1.0


def test_single_block_coherence_is_degenerate():
    """With one average, coherence is 1 everywhere - a known, expected trap."""
    rng = np.random.default_rng(7)
    x = rng.standard_normal(1024)
    _, coh = T.transfer_function(sig(x, "a"),
                                 sig(rng.standard_normal(1024), "b"),
                                 freq_resolution=1.0)
    assert coh.attributes["FFT_Nb_Averages"] == 1
    np.testing.assert_allclose(coh.y, 1.0, rtol=1e-6)


def test_averaging_complex_spectra_not_magnitudes():
    """Regression on the diagram's own warning.

    Averaging |Sxy| instead of Sxy would leave coherence at 1 even for
    unrelated signals; averaging H per block would too.
    """
    rng = np.random.default_rng(8)
    a, b = rng.standard_normal(1 << 14), rng.standard_normal(1 << 14)
    spectra = T.cross_spectra(sig(a), sig(b), freq_resolution=16.0)
    assert spectra.n_averages > 1
    assert np.iscomplexobj(spectra.sxy)
    # the complex average cancels; a magnitude average would not
    assert np.mean(np.abs(spectra.sxy)) < 0.5 * np.mean(
        np.sqrt(spectra.sxx * spectra.syy))


# -- H1 / H2 / H3 ------------------------------------------------------------
def test_estimators_agree_when_there_is_no_noise():
    rng = np.random.default_rng(9)
    x = rng.standard_normal(8192)
    spectra = T.cross_spectra(sig(x), sig(3.0 * x), freq_resolution=8.0)
    h1 = spectra.estimator("H1")[5:-5]
    h2 = spectra.estimator("H2")[5:-5]
    h3 = spectra.estimator("H3")[5:-5]
    np.testing.assert_allclose(np.abs(h1), 3.0, rtol=1e-6)
    np.testing.assert_allclose(np.abs(h2), 3.0, rtol=1e-6)
    np.testing.assert_allclose(np.abs(h3), 3.0, rtol=1e-6)


def test_h2_exceeds_h1_when_noise_is_on_the_response():
    """H1 under-estimates and H2 over-estimates with output noise."""
    rng = np.random.default_rng(10)
    n = 1 << 16
    x = rng.standard_normal(n)
    y = 2.0 * x + 1.5 * rng.standard_normal(n)
    spectra = T.cross_spectra(sig(x), sig(y), freq_resolution=8.0, overlap=0.5)
    mid = slice(5, -5)
    h1 = np.median(np.abs(spectra.estimator("H1")[mid]))
    h2 = np.median(np.abs(spectra.estimator("H2")[mid]))
    h3 = np.median(np.abs(spectra.estimator("H3")[mid]))
    assert h1 < h2
    assert h1 <= h3 <= h2


def test_unknown_estimator_rejected():
    rng = np.random.default_rng(11)
    x = rng.standard_normal(1024)
    spectra = T.cross_spectra(sig(x), sig(x), freq_resolution=1.0)
    with pytest.raises(ValueError, match="estimator"):
        spectra.estimator("H9")


# -- display types -----------------------------------------------------------
@pytest.fixture
def pair():
    rng = np.random.default_rng(12)
    x = rng.standard_normal(4096)
    y = 2.0 * np.roll(x, 3) + 0.2 * rng.standard_normal(4096)
    return T.transfer_function(sig(x, "ref", "N"), sig(y, "resp", "m/s^2"),
                               freq_resolution=4.0)


def test_display_types_match_the_labview_control():
    assert T.TF_DISPLAY_TYPES == (
        "Magnitude", "Phase (Rad)", "Phase Unwrap (Rad)",
        "Phase (Degree)", "Phase Unwrap (Degree)", "Coherence")


def test_magnitude_and_phase_views(pair):
    tf, _ = pair
    h = np.asarray(tf.attributes["TF_Complex"])
    np.testing.assert_allclose(
        T.format_transfer_function(tf, "Magnitude").y, np.abs(h))
    rad = T.format_transfer_function(tf, "Phase (Rad)")
    np.testing.assert_allclose(rad.y, np.angle(h))
    assert rad.y_unit == "rad"
    deg = T.format_transfer_function(tf, "Phase (Degree)")
    np.testing.assert_allclose(deg.y, np.degrees(np.angle(h)))
    assert deg.y_unit == "deg"


def test_unwrapped_phase_is_continuous(pair):
    tf, _ = pair
    wrapped = T.format_transfer_function(tf, "Phase (Rad)").y
    unwrapped = T.format_transfer_function(tf, "Phase Unwrap (Rad)").y
    assert np.abs(np.diff(wrapped)).max() > np.pi      # wraps present
    assert np.abs(np.diff(unwrapped)).max() < np.pi    # removed
    np.testing.assert_allclose(T.format_transfer_function(
        tf, "Phase Unwrap (Degree)").y, np.degrees(unwrapped))


def test_coherence_display_returns_the_coherence_signal(pair):
    tf, coh = pair
    assert T.format_transfer_function(tf, "Coherence", coh) is coh
    with pytest.raises(ValueError, match="coherence"):
        T.format_transfer_function(tf, "Coherence")


def test_invalid_display_type_rejected(pair):
    tf, _ = pair
    with pytest.raises(ValueError, match="transfer function type"):
        T.format_transfer_function(tf, "Nyquist")


def test_formatting_a_plain_signal_is_rejected():
    with pytest.raises(ValueError, match="TF_Complex"):
        T.format_transfer_function(sig(np.zeros(8)), "Magnitude")


# -- naming, units, provenance ------------------------------------------------
def test_naming_and_units(pair):
    tf, coh = pair
    assert tf.name == "resp / ref"
    assert tf.y_unit == "m/s^2/N"
    assert tf.x_unit == "Hz"
    assert coh.name == "Coherence (resp / ref)"
    assert coh.y_unit == ""
    assert tf.attributes["TF_Reference"] == "ref"
    assert tf.attributes["TF_Response"] == "resp"
    assert tf.attributes["TF_Estimator"] == "H1"
    assert tf.attributes["FFT_Window_Type"] == "bh_7term"   # SPWB's default


def test_matching_units_are_not_turned_into_a_ratio():
    rng = np.random.default_rng(13)
    x = rng.standard_normal(2048)
    tf, _ = T.transfer_function(sig(x, "a", "Pa"), sig(x, "b", "Pa"),
                                freq_resolution=4.0)
    assert tf.y_unit == "Pa"


def test_last_bin_is_duplicated_like_the_fft_path(pair):
    tf, coh = pair
    assert tf.y[-1] == tf.y[-2]
    assert coh.y[-1] == coh.y[-2]
    assert tf.n_samples == coh.n_samples


# -- multiple references x responses -----------------------------------------
def test_all_combinations_are_produced_reference_major():
    rng = np.random.default_rng(14)
    refs = [sig(rng.standard_normal(2048), f"ref{i}") for i in range(2)]
    resps = [sig(rng.standard_normal(2048), f"resp{j}") for j in range(3)]
    out = T.transfer_functions(refs, resps, freq_resolution=8.0)
    assert [tf.name for tf, _ in out] == [
        "resp0 / ref0", "resp1 / ref0", "resp2 / ref0",
        "resp0 / ref1", "resp1 / ref1", "resp2 / ref1"]


# -- input validation ---------------------------------------------------------
def test_mismatched_lengths_rejected():
    with pytest.raises(ValueError, match="same length"):
        T.transfer_function(sig(np.zeros(1024)), sig(np.zeros(512)),
                            freq_resolution=1.0)


def test_mismatched_sample_rates_rejected():
    a = Signal("a", np.zeros(1024), DT)
    b = Signal("b", np.zeros(1024), DT * 2)
    with pytest.raises(ValueError, match="sample rate"):
        T.transfer_function(a, b, freq_resolution=1.0)


def test_zero_reference_does_not_produce_nan():
    """A silent reference channel must give 0, not NaN/inf."""
    rng = np.random.default_rng(15)
    tf, coh = T.transfer_function(sig(np.zeros(2048), "silent"),
                                  sig(rng.standard_normal(2048), "resp"),
                                  freq_resolution=8.0)
    assert np.isfinite(tf.y).all()
    assert np.isfinite(coh.y).all()
    assert np.all(tf.y == 0.0)
