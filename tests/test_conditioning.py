"""Scale, offset, calibrate, normalise, truncate and resample."""
import numpy as np
import pytest

from spwb import Signal
from spwb.processing.dsp import conditioning as C

FS = 1000.0
DT = 1.0 / FS


def sig(name="s", amp=1.0, f=50.0, n=1000, unit="V"):
    t = np.arange(n) * DT
    return Signal(name, amp * np.sin(2 * np.pi * f * t), DT, y_unit=unit)


# -- scale / offset / calibrate ---------------------------------------------
def test_scale_multiplies_and_records_the_factor():
    out = C.scale(sig(amp=1.0), 9.81)
    assert np.abs(out.y).max() == pytest.approx(9.81, rel=1e-3)
    assert out.attributes["Scale_Factor"] == 9.81


def test_offset_shifts_the_mean():
    out = C.offset(sig(), 5.0)
    assert out.y.mean() == pytest.approx(5.0, abs=1e-3)
    assert out.attributes["DC_Offset"] == 5.0


def test_offset_can_remove_the_mean():
    s = C.offset(sig(), 3.0)
    centred = C.offset(s, -s.y.mean())
    assert centred.y.mean() == pytest.approx(0.0, abs=1e-12)


def test_calibrate_scales_then_offsets_in_that_order():
    """factor applies to the raw signal; dc is added in calibrated units."""
    s = Signal("raw", np.array([1.0, 2.0, 3.0]), DT)
    out = C.calibrate(s, factor=10.0, dc=1.0)
    np.testing.assert_allclose(out.y, [11.0, 21.0, 31.0])


def test_calibrate_can_rename_and_reunit():
    out = C.calibrate(sig("ch0", unit="V"), factor=100.0, name="Accel X",
                      unit="m/s^2")
    assert out.name == "Accel X" and out.y_unit == "m/s^2"
    assert out.attributes["Channel Name"] == "Accel X"
    assert out.attributes["Channel Unit"] == "m/s^2"


def test_calibrate_defaults_change_nothing_but_the_provenance():
    original = sig()
    out = C.calibrate(original)
    np.testing.assert_array_equal(out.y, original.y)
    assert out.name == original.name and out.y_unit == original.y_unit


def test_annotate_marks_the_name():
    assert C.scale(sig("a"), 2.0, annotate=True).name == "a (x2)"
    assert C.offset(sig("a"), -1.5, annotate=True).name == "a (-1.5)"


# -- normalisation -----------------------------------------------------------
@pytest.fixture
def pair():
    return [sig("loud", amp=4.0), sig("quiet", amp=1.0)]


def test_normalize_to_itself_makes_every_signal_unit_peak(pair):
    out, max_all = C.normalize(pair, "To itself")
    for s in out:
        assert np.abs(s.y).max() == pytest.approx(1.0, rel=1e-6)
    assert max_all == pytest.approx(4.0, rel=1e-6)


def test_normalize_to_all_preserves_relative_levels(pair):
    out, max_all = C.normalize(pair, "To the max levels of ALL the signals")
    peaks = [np.abs(s.y).max() for s in out]
    assert peaks[0] == pytest.approx(1.0, rel=1e-6)
    assert peaks[1] == pytest.approx(0.25, rel=1e-6)   # 1:4 ratio kept
    assert max_all == pytest.approx(4.0, rel=1e-6)


def test_normalize_none_passes_through(pair):
    out, max_all = C.normalize(pair, "None")
    for before, after in zip(pair, out, strict=True):
        np.testing.assert_array_equal(after.y, before.y)
    assert max_all == pytest.approx(4.0, rel=1e-6)


def test_normalize_returns_copies_not_the_originals(pair):
    out, _ = C.normalize(pair, "None")
    out[0].y[0] = 999.0
    assert pair[0].y[0] != 999.0


def test_normalize_leaves_an_all_zero_signal_alone():
    flat = Signal("silent", np.zeros(100), DT)
    out, max_all = C.normalize([flat, sig(amp=2.0)], "To itself")
    assert np.all(out[0].y == 0.0)
    assert max_all == pytest.approx(2.0, rel=1e-6)


def test_unknown_normalization_rejected(pair):
    with pytest.raises(ValueError, match="normalization option"):
        C.normalize(pair, "To eleven")


# -- truncate ----------------------------------------------------------------
def test_truncate_keeps_the_requested_span():
    out = C.truncate(sig(n=1000), 0.2, 0.5)
    assert out.t0 == pytest.approx(0.2, abs=DT)
    assert out.duration == pytest.approx(0.3, abs=2 * DT)


def test_truncate_respects_t0():
    s = Signal("s", np.arange(1000, dtype=float), DT, t0=10.0)
    out = C.truncate(s, 10.1, 10.2)
    assert out.t0 == pytest.approx(10.1, abs=DT)
    assert out.y[0] == pytest.approx(100.0, abs=1.0)


def test_truncate_accepts_reversed_limits():
    a = C.truncate(sig(), 0.5, 0.2)
    b = C.truncate(sig(), 0.2, 0.5)
    np.testing.assert_array_equal(a.y, b.y)


def test_truncate_clips_to_the_available_range():
    out = C.truncate(sig(n=1000), -5.0, 500.0)
    assert out.n_samples == 1000


def test_truncate_outside_the_signal_is_rejected():
    with pytest.raises(ValueError, match="no samples"):
        C.truncate(sig(n=1000), 50.0, 60.0)


# -- resample ----------------------------------------------------------------
def test_resample_down_halves_the_rate_and_keeps_the_tone():
    from spwb.processing.dsp import auto_power_spectrums
    original = sig(amp=2.0, f=50.0, n=8000)
    out = C.resample(original, FS / 2)
    assert out.fs == pytest.approx(FS / 2)
    assert out.n_samples == pytest.approx(4000, abs=2)
    spec = auto_power_spectrums(out, freq_resolution=2.0)
    peak_hz = spec.t[int(np.argmax(spec.y))]
    assert peak_hz == pytest.approx(50.0, abs=2.0)
    assert spec.y.max() == pytest.approx(2.0 ** 2 / 2, rel=0.05)


def test_resample_up_doubles_the_rate():
    out = C.resample(sig(n=1000), FS * 2)
    assert out.fs == pytest.approx(FS * 2)
    assert out.n_samples == pytest.approx(2000, abs=2)


def test_resample_records_both_rates():
    out = C.resample(sig(), 500.0)
    assert out.attributes["Resampled_From_Hz"] == pytest.approx(FS)
    assert out.attributes["Resampled_To_Hz"] == pytest.approx(500.0)


def test_resample_to_the_same_rate_is_a_no_op():
    original = sig()
    out = C.resample(original, FS)
    np.testing.assert_array_equal(out.y, original.y)


def test_resample_filters_rather_than_aliasing():
    """A tone above the new Nyquist must be attenuated, not folded down."""
    from spwb.processing.dsp import auto_power_spectrums
    high = sig(amp=1.0, f=400.0, n=8000)       # 400 Hz, new Nyquist is 125 Hz
    out = C.resample(high, 250.0)
    spec = auto_power_spectrums(out, freq_resolution=2.0)
    assert spec.y.max() < 0.05                  # nothing strong survives


def test_invalid_resample_rate_rejected():
    with pytest.raises(ValueError, match="positive"):
        C.resample(sig(), 0.0)
