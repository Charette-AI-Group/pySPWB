"""Spectral function types, display options and acoustic weighting.

These are the enums the FFT window exposes (strings recovered verbatim from
SPWB's .ctl files). The reference values come from analytical identities:
a sine of known amplitude must read the right number in every one of the
eight function types.
"""
import math

import numpy as np
import pytest

from spwb import Signal
from spwb.processing.dsp import spectral as S

AMPLITUDE = 3.0
FREQ = 128.0
FS = 1024.0


@pytest.fixture
def spectrum():
    dt = 1.0 / FS
    t = np.arange(4096) * dt
    sig = Signal("sine", AMPLITUDE * np.sin(2 * np.pi * FREQ * t), dt,
                 y_unit="Pa")
    return S.auto_power_spectrums(sig, freq_resolution=1.0, window="hanning")


def test_spectrum_carries_the_source_unit_forward(spectrum):
    """Without this, format_spectrum labels everything 'EU' and the
    automatic dB reference can never resolve."""
    assert spectrum.attributes["Channel Unit"] == "Pa"


@pytest.fixture
def bin_index(spectrum):
    return int(round(FREQ / spectrum.dt))


def test_enum_lists_match_the_labview_controls():
    assert len(S.SPECTRAL_FUNCTION_TYPES) == 8
    assert S.SPECTRAL_FUNCTION_TYPES[0] == "Auto Spectrum - (EU RMS)"
    assert S.SPECTRAL_FUNCTION_TYPES[6] == "Power Spectrum Density - (EU RMS²/Hz)"
    assert len(S.SPECTRUM_DISPLAY_OPTIONS) == 7
    assert S.SPECTRUM_DISPLAY_OPTIONS[3] == "dB - Sound SPL (ref 20E-6 Pa)"
    assert S.ACOUSTIC_WEIGHTINGS == ("Linear", "A-weighting")


@pytest.mark.parametrize("function_type, expected", [
    ("Auto Spectrum - (EU RMS)", AMPLITUDE / math.sqrt(2)),
    ("Auto Spectrum - (EU Peak)", AMPLITUDE),
    ("Power Spectrum - (EU RMS²)", AMPLITUDE ** 2 / 2),
    ("Power Spectrum - (EU Peak²)", AMPLITUDE ** 2),
])
def test_non_density_function_types(spectrum, bin_index, function_type, expected):
    out = S.format_spectrum(spectrum, function_type=function_type)
    assert out.y[bin_index] == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize("function_type, base", [
    ("Auto Spectrum Density - (EU RMS/rtHz)", AMPLITUDE / math.sqrt(2)),
    ("Auto Spectrum Density - (EU Peak/rtHz)", AMPLITUDE),
    ("Power Spectrum Density - (EU RMS²/Hz)", AMPLITUDE ** 2 / 2),
    ("Power Spectrum Density - (EU Peak²/Hz)", AMPLITUDE ** 2),
])
def test_density_function_types_divide_by_enbw_times_df(
        spectrum, bin_index, function_type, base):
    """Density = power / (ENBW * df); amplitude forms take the sqrt of that."""
    enbw = spectrum.attributes["FFT_EQ_Noise_BW"]
    norm = enbw * spectrum.dt
    squared = "Power" in function_type
    expected = base / norm if squared else base / math.sqrt(norm)
    out = S.format_spectrum(spectrum, function_type=function_type)
    assert out.y[bin_index] == pytest.approx(expected, rel=1e-6)


def test_units_describe_the_scaling(spectrum):
    def unit(ft):
        return S.format_spectrum(spectrum, function_type=ft).y_unit
    assert unit("Auto Spectrum - (EU RMS)") == "Pa RMS"
    assert unit("Power Spectrum - (EU RMS²)") == "Pa² RMS²"
    assert unit("Auto Spectrum Density - (EU Peak/rtHz)") == "Pa Peak/√Hz"
    assert unit("Power Spectrum Density - (EU RMS²/Hz)") == "Pa² RMS²/Hz"


# -- dB display options ------------------------------------------------------
def test_db_no_reference_is_20log10_of_amplitude(spectrum, bin_index):
    out = S.format_spectrum(spectrum, function_type="Auto Spectrum - (EU RMS)",
                            display_option="dB - NO reference value")
    assert out.y[bin_index] == pytest.approx(
        20 * math.log10(AMPLITUDE / math.sqrt(2)), rel=1e-6)
    assert out.y_unit == "dB"


def test_db_on_a_squared_type_uses_10log10(spectrum, bin_index):
    out = S.format_spectrum(spectrum,
                            function_type="Power Spectrum - (EU RMS²)",
                            display_option="dB - NO reference value")
    assert out.y[bin_index] == pytest.approx(
        10 * math.log10(AMPLITUDE ** 2 / 2), rel=1e-6)


def test_spl_reference(spectrum, bin_index):
    out = S.format_spectrum(spectrum, display_option="dB - Sound SPL (ref 20E-6 Pa)")
    assert out.y[bin_index] == pytest.approx(
        20 * math.log10(AMPLITUDE / math.sqrt(2) / 20e-6), rel=1e-6)
    assert out.y_unit == "dB ref 20E-6 Pa"     # SPWB's own wording


def test_automatic_reference_picks_by_unit(spectrum, bin_index):
    """Pa -> 20 uPa, exactly like the explicit SPL option."""
    auto = S.format_spectrum(spectrum,
                             display_option="dB - Automatic reference value")
    spl = S.format_spectrum(spectrum,
                            display_option="dB - Sound SPL (ref 20E-6 Pa)")
    assert auto.y[bin_index] == pytest.approx(spl.y[bin_index], rel=1e-12)


def test_automatic_reference_falls_back_to_unity(spectrum, bin_index):
    spectrum.attributes["Channel Unit"] = "V"       # no standard reference
    out = S.format_spectrum(spectrum,
                            display_option="dB - Automatic reference value")
    assert out.y[bin_index] == pytest.approx(
        20 * math.log10(AMPLITUDE / math.sqrt(2)), rel=1e-6)


def test_db_of_zero_is_floored_not_infinite(spectrum):
    """Empty bins must not produce -inf or absurd values that wreck autoscale."""
    padded = spectrum.with_(y=np.concatenate([spectrum.y, [0.0]]))
    out = S.format_spectrum(padded, display_option="dB - NO reference value")
    assert np.isfinite(out.y).all()
    assert out.y.max() - out.y.min() == pytest.approx(S.DB_DYNAMIC_RANGE)


def test_db_floor_is_relative_to_the_peak(spectrum):
    """Scaling the signal shifts every dB value, including the floor."""
    louder = spectrum.with_(y=spectrum.y * 100.0)
    a = S.format_spectrum(spectrum, display_option="dB - NO reference value")
    b = S.format_spectrum(louder, display_option="dB - NO reference value")
    assert b.y.max() - a.y.max() == pytest.approx(20 * math.log10(10.0), rel=1e-9)


def test_db_of_an_all_zero_spectrum_is_finite(spectrum):
    out = S.format_spectrum(spectrum.with_(y=np.zeros(spectrum.n_samples)),
                            display_option="dB - NO reference value")
    assert np.isfinite(out.y).all()


# -- A-weighting -------------------------------------------------------------
@pytest.mark.parametrize("freq, expected_db, tol", [
    (1000.0, 0.0, 0.05),      # A-weighting is 0 dB at 1 kHz by definition
    (100.0, -19.1, 0.2),      # IEC 61672 table values
    (500.0, -3.2, 0.2),
    (2000.0, 1.2, 0.2),
    (10000.0, -2.5, 0.3),
])
def test_a_weighting_matches_iec_61672(freq, expected_db, tol):
    assert S.a_weighting(np.array([freq]))[0] == pytest.approx(expected_db,
                                                               abs=tol)


def test_a_weighting_at_dc_is_finite_and_very_negative():
    value = S.a_weighting(np.array([0.0]))[0]
    assert np.isfinite(value) and value < -100


@pytest.mark.parametrize("function_type, domain_factor", [
    ("Auto Spectrum - (EU RMS)", 20.0),      # amplitude -> 10^(A/20)
    ("Power Spectrum - (EU RMS²)", 10.0),    # power     -> 10^(A/10)
])
def test_weighting_enters_in_the_right_domain(spectrum, bin_index,
                                              function_type, domain_factor):
    linear = S.format_spectrum(spectrum, function_type=function_type)
    weighted = S.format_spectrum(spectrum, function_type=function_type,
                                 weighting="A-weighting")
    a_db = S.a_weighting(np.array([FREQ]))[0]
    expected = linear.y[bin_index] * 10 ** (a_db / domain_factor)
    assert weighted.y[bin_index] == pytest.approx(expected, rel=1e-9)
    assert "[A-Weighted]" in weighted.y_unit


def test_weighting_on_a_db_display_is_added_directly(spectrum, bin_index):
    plain = S.format_spectrum(spectrum,
                              display_option="dB - NO reference value")
    weighted = S.format_spectrum(spectrum,
                                 display_option="dB - NO reference value",
                                 weighting="A-weighting")
    a_db = S.a_weighting(np.array([FREQ]))[0]
    assert weighted.y[bin_index] == pytest.approx(plain.y[bin_index] + a_db,
                                                  rel=1e-9)


def test_linear_weighting_is_a_pass_through(spectrum):
    a = S.format_spectrum(spectrum, weighting="Linear")
    b = S.format_spectrum(spectrum)
    np.testing.assert_array_equal(a.y, b.y)


# -- provenance and validation -----------------------------------------------
def test_attributes_record_the_display_settings(spectrum):
    out = S.format_spectrum(spectrum,
                            function_type="Power Spectrum - (EU RMS²)",
                            display_option="dB - Velocity (ref 1E-9 m/s)",
                            weighting="A-weighting")
    assert out.attributes["FFT_Function_Type"] == "Power Spectrum - (EU RMS²)"
    assert out.attributes["FFT_Display_Option"] == "dB - Velocity (ref 1E-9 m/s)"
    assert out.attributes["FFT_Acoustic_Weighting"] == "A-weighting"
    assert out.attributes["FFT_Window_Type"] == "hanning"   # kept from source


@pytest.mark.parametrize("kwargs, message", [
    (dict(function_type="Nope"), "function type"),
    (dict(display_option="Nope"), "display option"),
    (dict(weighting="C-weighting"), "weighting"),
])
def test_invalid_options_rejected(spectrum, kwargs, message):
    with pytest.raises(ValueError, match=message):
        S.format_spectrum(spectrum, **kwargs)


# -- energy band -------------------------------------------------------------
def test_band_rms_recovers_the_tone_amplitude(spectrum):
    """The ENBW division is what makes this come out right."""
    assert S.band_rms(spectrum, 0.0, FS / 2) == pytest.approx(
        AMPLITUDE / math.sqrt(2), rel=1e-3)


def test_band_rms_is_window_independent(spectrum):
    """A correct band measure must not depend on the analysis window."""
    dt = 1.0 / FS
    t = np.arange(4096) * dt
    sig = Signal("sine", AMPLITUDE * np.sin(2 * np.pi * FREQ * t), dt)
    for window_name in ("rectangular", "hanning", "flat_top", "blackman"):
        raw = S.auto_power_spectrums(sig, freq_resolution=1.0,
                                     window=window_name)
        assert S.band_rms(raw, 0.0, FS / 2) == pytest.approx(
            AMPLITUDE / math.sqrt(2), rel=5e-3), window_name


def test_band_excludes_content_outside_it(spectrum):
    assert S.band_rms(spectrum, 0.0, FREQ / 2) < 0.01 * AMPLITUDE
    assert S.band_rms(spectrum, FREQ * 2, FS / 2) < 0.01 * AMPLITUDE


def test_band_limits_may_be_given_in_either_order(spectrum):
    assert S.band_power(spectrum, 200.0, 100.0) == pytest.approx(
        S.band_power(spectrum, 100.0, 200.0))


def test_two_tones_add_in_power(spectrum):
    dt = 1.0 / FS
    t = np.arange(4096) * dt
    sig = Signal("two", 3.0 * np.sin(2 * np.pi * 100 * t)
                 + 4.0 * np.sin(2 * np.pi * 300 * t), dt)
    raw = S.auto_power_spectrums(sig, freq_resolution=1.0, window="hanning")
    total = S.band_rms(raw, 0.0, FS / 2)
    assert total == pytest.approx(math.sqrt((9 + 16) / 2), rel=5e-3)
