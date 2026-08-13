"""WAV IO: normalisation, the filename scale convention, and save options."""
import numpy as np
import pytest
from scipy.io import wavfile

from spwb import Signal
from spwb.processing.io import wave as W

FS = 8000


def sig(name="tone", amp=1.0, f=200.0, n=4000, fs=FS, unit=""):
    dt = 1.0 / fs
    t = np.arange(n) * dt
    return Signal(name, amp * np.sin(2 * np.pi * f * t), dt, y_unit=unit)


# -- the filename scale convention -------------------------------------------
@pytest.mark.parametrize("name, scale, unit", [
    ("Accel_scale_9.81_m-per-s2.wav", 9.81, "m/s2"),
    ("Mic_scale_2.5_Pa.wav", 2.5, "Pa"),
    ("run_SCALE_10.0_Pa.wav", 10.0, "Pa"),        # keyword is case-insensitive
    ("x_scale_0.5.wav", 0.5, ""),                 # unit optional
    ("x_scale_-3.25_V.wav", -3.25, "V"),
    ("plain.wav", None, ""),                      # no keyword
    ("x_scale_notanumber_V.wav", None, ""),       # keyword, unparsable value
    ("x_scale.wav", None, ""),                    # keyword with nothing after
])
def test_parse_scale_from_filename(name, scale, unit):
    got_scale, got_unit = W.parse_scale_from_filename(name)
    assert got_scale == scale
    assert got_unit == unit


def test_scale_filename_round_trips():
    stem = W.scale_filename("Accel X", 9.81, "m/s2")
    assert stem == "Accel X_scale_9.81_m-per-s2"
    scale, unit = W.parse_scale_from_filename(stem + ".wav")
    assert scale == pytest.approx(9.81)
    assert unit == "m/s2"


def test_scale_filename_omits_an_empty_unit():
    assert W.scale_filename("x", 2.0) == "x_scale_2.00"


# -- reading -----------------------------------------------------------------
@pytest.fixture
def mono_int16(tmp_path):
    path = tmp_path / "tone.wav"
    data = np.round(np.sin(2 * np.pi * 200 * np.arange(4000) / FS)
                    * 32767).astype(np.int16)
    wavfile.write(str(path), FS, data)
    return path


def test_read_normalises_integers_to_unit_range(mono_int16):
    (s,) = W.read_wave(mono_int16)
    assert s.n_samples == 4000
    assert s.fs == pytest.approx(FS)
    assert s.x_unit == "sec"                 # SPWB writes "sec" here, not "s"
    assert np.abs(s.y).max() == pytest.approx(1.0, rel=1e-4)
    assert s.attributes["WAV Scale Factor"] == 1.0
    assert s.attributes["WAV Sample Format"] == "int16"
    assert s.attributes["Data Source"].endswith("tone.wav")


@pytest.mark.parametrize("dtype, peak", [
    (np.int16, 32767), (np.int32, 2147483647), (np.float32, 1.0),
])
def test_every_sample_format_normalises_to_unit_range(tmp_path, dtype, peak):
    """Integers divide by full scale (2^bits-1), so the positive peak lands
    just under 1.0 - the two's-complement range is asymmetric."""
    path = tmp_path / f"{np.dtype(dtype).name}.wav"
    wavfile.write(str(path), FS, np.array([0, peak, -peak], dtype))
    (s,) = W.read_wave(path)
    assert np.abs(s.y).max() == pytest.approx(1.0, rel=1e-4)
    assert np.abs(s.y).max() <= 1.0


def test_integer_full_scale_negative_reaches_exactly_minus_one(tmp_path):
    path = tmp_path / "min.wav"
    wavfile.write(str(path), FS, np.array([-32768], np.int16))
    (s,) = W.read_wave(path)
    assert s.y[0] == pytest.approx(-1.0)


def test_unsigned_8_bit_is_centred_on_128(tmp_path):
    path = tmp_path / "u8.wav"
    wavfile.write(str(path), FS, np.array([128, 255, 0], np.uint8))
    (s,) = W.read_wave(path)
    assert s.y[0] == pytest.approx(0.0)         # 128 is silence, not +1
    assert s.y[1] == pytest.approx(127 / 128)
    assert s.y[2] == pytest.approx(-1.0)


def test_filename_scale_is_applied_and_names_are_cleaned(tmp_path):
    path = tmp_path / "Accel X_scale_9.81_m-per-s2.wav"
    wavfile.write(str(path), FS, np.array([0, 32767, -32767], np.int16))
    (s,) = W.read_wave(path)
    assert s.y[1] == pytest.approx(9.81, rel=1e-4)
    assert s.y_unit == "m/s2"
    assert s.name == "Accel X"                  # scale decoration stripped
    assert s.attributes["Channel Unit"] == "m/s2"


def test_explicit_scale_and_unit_override_the_filename(tmp_path):
    path = tmp_path / "x_scale_9.81_m-per-s2.wav"
    wavfile.write(str(path), FS, np.array([0, 32767], np.int16))
    (s,) = W.read_wave(path, scale=2.0, unit="Pa")
    assert s.y[1] == pytest.approx(2.0, rel=1e-4)
    assert s.y_unit == "Pa"


def test_multichannel_splits_into_named_signals(tmp_path):
    path = tmp_path / "stereo.wav"
    data = np.zeros((100, 2), np.int16)
    data[:, 0] = 1000
    data[:, 1] = -2000
    wavfile.write(str(path), FS, data)
    signals = W.read_wave(path)
    assert [s.name for s in signals] == ["stereo Ch1", "stereo Ch2"]
    assert signals[0].attributes["WAV Channel"] == 1
    assert signals[1].y[0] < 0


def test_channel_offset_keeps_names_unique(tmp_path):
    path = tmp_path / "a.wav"
    wavfile.write(str(path), FS, np.zeros((10, 2), np.int16))
    signals = W.read_wave(path, channel_offset=4)
    assert [s.name for s in signals] == ["a Ch5", "a Ch6"]


def test_read_multiple_files_continues_channel_numbering(tmp_path):
    paths = []
    for name in ("one", "two"):
        p = tmp_path / f"{name}.wav"
        wavfile.write(str(p), FS, np.zeros((10, 2), np.int16))
        paths.append(p)
    signals = W.read_waves(paths)
    assert [s.name for s in signals] == ["one Ch1", "one Ch2",
                                         "two Ch3", "two Ch4"]


def test_contents_reports_without_importing(tmp_path):
    path = tmp_path / "probe_scale_4.0_Pa.wav"
    wavfile.write(str(path), FS, np.zeros((800, 2), np.int16))
    info = W.wave_contents(path)
    assert info.n_channels == 2 and info.n_samples == 800
    assert info.fs == FS and info.duration == pytest.approx(0.1)
    assert info.scale == pytest.approx(4.0) and info.unit == "Pa"
    assert info.dtype == "int16"


# -- writing -----------------------------------------------------------------
def test_write_normalises_and_encodes_the_factor(tmp_path):
    s = sig(amp=9.81, unit="m/s2")
    (written,) = W.write_wave(tmp_path / "accel.wav", [s])
    assert "scale" in written.name
    fs, raw = wavfile.read(str(written))
    assert fs == FS
    assert np.abs(raw).max() >= 32000            # uses full scale
    scale, unit = W.parse_scale_from_filename(written)
    assert scale == pytest.approx(9.81, rel=1e-2)
    assert unit == "m/s2"


def test_round_trip_preserves_amplitude_and_unit(tmp_path):
    original = sig(amp=9.81, unit="m/s2")
    (written,) = W.write_wave(tmp_path / "accel.wav", [original])
    (back,) = W.read_wave(written)
    assert back.fs == pytest.approx(original.fs)
    assert back.n_samples == original.n_samples
    assert back.y_unit == "m/s2"
    # 16-bit quantisation over a +-9.81 range
    np.testing.assert_allclose(back.y, original.y, atol=9.81 / 32767 * 2)


@pytest.mark.parametrize("subtype, tolerance", [
    ("int16", 2 / 32767), ("int32", 1e-6), ("float32", 1e-6),
])
def test_round_trip_for_each_sample_format(tmp_path, subtype, tolerance):
    original = sig(amp=1.0)
    (written,) = W.write_wave(tmp_path / f"{subtype}.wav", [original],
                              subtype=subtype)
    (back,) = W.read_wave(written)
    np.testing.assert_allclose(back.y, original.y, atol=tolerance * 2)


def test_desired_level_limits_the_peak(tmp_path):
    (written,) = W.write_wave(tmp_path / "quiet.wav", [sig(amp=5.0)],
                              desired_level=0.5)
    _, raw = wavfile.read(str(written))
    assert np.abs(raw).max() == pytest.approx(0.5 * 32767, rel=0.01)
    (back,) = W.read_wave(written)
    assert np.abs(back.y).max() == pytest.approx(5.0, rel=0.01)


def test_encode_scale_can_be_turned_off(tmp_path):
    (written,) = W.write_wave(tmp_path / "plain.wav", [sig(amp=3.0)],
                              encode_scale=False)
    assert written.name == "plain.wav"
    (back,) = W.read_wave(written)
    assert np.abs(back.y).max() == pytest.approx(1.0, rel=1e-3)   # raw +-1


def test_one_file_per_signal_writes_one_each(tmp_path):
    signals = [sig("a", amp=1.0), sig("b", amp=2.0)]
    written = W.write_wave(tmp_path / "out.wav", signals)
    assert len(written) == 2
    assert all(p.exists() for p in written)
    assert "a" in written[0].name and "b" in written[1].name
    # each is normalised on its own, so both hit full scale
    for path in written:
        _, raw = wavfile.read(str(path))
        assert np.abs(raw).max() >= 32000


def test_concatenate_joins_signals_in_time(tmp_path):
    signals = [sig("a", n=1000), sig("b", n=500)]
    (written,) = W.write_wave(tmp_path / "joined.wav", signals,
                              save_option=W.SAVE_OPTIONS[1])
    (back,) = W.read_wave(written)
    assert back.n_samples == 1500


def test_stereo_places_channels_in_order(tmp_path):
    left = Signal("L", np.full(100, 0.5), 1 / FS)
    right = Signal("R", np.full(100, -0.25), 1 / FS)
    (written,) = W.write_wave(tmp_path / "st.wav", [left, right],
                              save_option=W.SAVE_OPTIONS[2])
    signals = W.read_wave(written)
    assert len(signals) == 2
    assert signals[0].y[0] > 0 and signals[1].y[0] < 0
    # one shared factor, so the 2:1 level ratio survives
    assert abs(signals[0].y[0] / signals[1].y[0]) == pytest.approx(2.0, rel=1e-3)


def test_stereo_swapped_reverses_the_channels(tmp_path):
    left = Signal("L", np.full(100, 0.5), 1 / FS)
    right = Signal("R", np.full(100, -0.25), 1 / FS)
    (written,) = W.write_wave(tmp_path / "sw.wav", [left, right],
                              save_option=W.SAVE_OPTIONS[3])
    signals = W.read_wave(written)
    assert signals[0].y[0] < 0 and signals[1].y[0] > 0


# -- validation --------------------------------------------------------------
def test_mixed_sample_rates_are_rejected(tmp_path):
    a = sig("a", fs=8000)
    b = sig("b", fs=44100)
    with pytest.raises(ValueError, match="one sample rate"):
        W.write_wave(tmp_path / "x.wav", [a, b])


def test_stereo_needs_exactly_two_signals(tmp_path):
    with pytest.raises(ValueError, match="exactly 2"):
        W.write_wave(tmp_path / "x.wav", [sig()], save_option=W.SAVE_OPTIONS[2])


def test_stereo_needs_equal_lengths(tmp_path):
    with pytest.raises(ValueError, match="equal-length"):
        W.write_wave(tmp_path / "x.wav", [sig(n=100), sig(n=200)],
                     save_option=W.SAVE_OPTIONS[2])


@pytest.mark.parametrize("kwargs, message", [
    (dict(save_option="Nope"), "save option"),
    (dict(subtype="int64"), "sample format"),
    (dict(desired_level=0.0), "desired_level"),
    (dict(desired_level=1.5), "desired_level"),
])
def test_invalid_write_options_rejected(tmp_path, kwargs, message):
    with pytest.raises(ValueError, match=message):
        W.write_wave(tmp_path / "x.wav", [sig()], **kwargs)


def test_writing_nothing_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="no signals"):
        W.write_wave(tmp_path / "x.wav", [])


def test_all_zero_signal_does_not_divide_by_zero(tmp_path):
    flat = Signal("silence", np.zeros(100), 1 / FS)
    (written,) = W.write_wave(tmp_path / "z.wav", [flat])
    (back,) = W.read_wave(written)
    assert np.all(back.y == 0.0)


def test_clipping_is_bounded_not_wrapped(tmp_path):
    """A signal already beyond +-1 must clip, never wrap to the opposite sign."""
    hot = Signal("hot", np.array([2.0, -2.0, 0.0]), 1 / FS)
    (written,) = W.write_wave(tmp_path / "hot.wav", [hot], encode_scale=False,
                              desired_level=1.0)
    _, raw = wavfile.read(str(written))
    assert raw[0] > 0 and raw[1] < 0
