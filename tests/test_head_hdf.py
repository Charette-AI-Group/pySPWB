"""HEAD acoustics HDF: the container format, parsed directly.

The format is self-describing - an ASCII key/value header padded to
``start of data``, then raw samples - so these tests build the bytes
themselves, the same way ``test_rpc.py`` does. That pins the layout the
reader claims rather than whatever a fixture happens to contain.

The synthetic files are modelled on four real ArtemiS recordings the reader
was developed against (a 1 kHz sine, a sweep, uniform random noise and a
measured accelerometer channel). ``test_real_artemis_files`` reads those
directly and skips when they are not present, since they are not ours to
commit.
"""
import os
import pathlib

import numpy as np
import pytest

from spwb.processing.io import (
    HeadFormatError,
    head_hdf_contents,
    read_head_hdf,
    read_head_hdf_header,
)

DT = 1.0 / 8192.0
START_OF_DATA = 65536

#: the four recordings used to develop the reader; set SPWB_ARTEMIS_DIR to
#: point the optional test at a copy elsewhere
REAL_DIR = pathlib.Path(os.environ.get(
    "SPWB_ARTEMIS_DIR",
    r"D:\data\dataSets\2014 & prior - devData\devData"
    r"\DSP Benchmark Signals\Artemis"))


def field(key, value):
    return f"{key}:".ljust(35) + str(value)


def build_hdf(path, channels, *, n=1024, dt=DT, t0=0.0, kind="Time data",
              byte_order="Intel", dtype="FLOAT32", data_org="a1b1 a2b2",
              start_of_data=START_OF_DATA, recorded=True, data=None):
    """Write a HEAD acoustics HDF file.

    ``channels`` is a list of ``(name, unit, quantity, samples)``. Samples
    are interleaved across channels, which is what ``a1b1 a2b2`` means.
    """
    lines = [
        ";",
        "; Copyright 1999 HEAD acoustics GmbH, Germany",
        ";",
        field("version", 4),
        field("release", 5),
    ]
    if recorded:
        lines += [";#" + field("date of recording", "30063977-4197303808"),
                  ";" + " " * 34 + "3/6/2010 15:17:00.000"]
    lines += [
        field("byte order", byte_order),
        field("kind", kind),
        field("start of data", start_of_data),
        field("nbr of abscissa", 1),
        field("nbr of channel", len(channels)),
        ";#" + field("nbr of subchannel", 0),
        field("nbr of extra fields", 0),
        field("idx order", 1),
        field("ch order", 1),
        field("data org", data_org),
        field("scan mode", "simultaneous"),
        ";",
        field("abscissa definition", 1),
        field("name str", "time"),
        field("abbreviation str", "t"),
        field("physical quantity", "time"),
        field("physical unit", "s"),
        field("first value", t0),
        field("delta value", f"{dt:.12g}"),
        field("nbr of scans", n),
        field("distribution func", "linear"),
    ]
    for i, (name, unit, quantity, _samples) in enumerate(channels, start=1):
        lines += [
            ";",
            field("channel definition", i),
            field("name str", name),
            field("abbreviation str", name[:2]),
            field("title str", f"{name} description"),
            field("physical channel nbr", i),
            field("physical quantity", quantity),
            field("physical unit", unit),
            field("calibration", 94),
            field("composition", "sample"),
            field("implementation type", dtype),
        ]

    header = "\r\n".join(lines).encode("latin-1")
    if len(header) > start_of_data:
        raise AssertionError("test header does not fit before start of data")
    header = header.ljust(start_of_data, b"\t")

    if data is None:
        order = "<" if byte_order.upper() == "INTEL" else ">"
        np_dtype = np.dtype(order + {"FLOAT32": "f4", "FLOAT64": "f8",
                                     "INT16": "i2"}[dtype])
        stacked = np.array([s[:n] for _n, _u, _q, s in channels])
        data = stacked.T.astype(np_dtype).tobytes()

    path.write_bytes(header + data)
    return path


def sine(n=1024, freq=1000.0, dt=DT, amp=1.0):
    return amp * np.sin(2 * np.pi * freq * np.arange(n) * dt)


@pytest.fixture
def hdf_path(tmp_path):
    return build_hdf(tmp_path / "Sine 1kHz.hdf",
                     [("Test", "Pa", "pressure", sine())])


# -- the header ------------------------------------------------------------
def test_header_exposes_the_layout(hdf_path):
    header = read_head_hdf_header(hdf_path)

    assert header.kind == "Time data"
    assert header.byte_order == "<"
    assert header.data_offset == START_OF_DATA
    assert header.n_channels == 1
    assert header.n_samples == 1024
    assert header.dt == pytest.approx(DT)
    assert header.t0 == 0.0
    assert header.x_unit == "s"
    assert header.recorded == "3/6/2010 15:17:00.000"


def test_repeated_keys_belong_to_their_block(hdf_path):
    """'name str' appears in both blocks and means different things."""
    header = read_head_hdf_header(hdf_path)

    assert header.abscissas[0]["name str"] == "time"
    assert header.abscissas[0]["physical unit"] == "s"
    assert header.channels[0]["name str"] == "Test"
    assert header.channels[0]["physical unit"] == "Pa"
    # the top-level block must not have swallowed either of them
    assert "name str" not in header.top


def test_disabled_fields_are_kept_separately(hdf_path):
    header = read_head_hdf_header(hdf_path)

    assert header.optional["nbr of subchannel"] == "0"
    assert header.optional["date of recording"] == "30063977-4197303808"
    # the readable date rides on the plain comment line below the key
    assert header.optional["date of recording text"] == "3/6/2010 15:17:00.000"
    assert "nbr of subchannel" not in header.top


# -- reading ---------------------------------------------------------------
def test_samples_decode_to_the_right_values(hdf_path):
    expected = sine()

    signal, = read_head_hdf(hdf_path)

    assert signal.name == "Test"
    assert signal.y_unit == "Pa"
    assert signal.x_unit == "s"
    assert signal.dt == pytest.approx(DT)
    assert signal.n_samples == 1024
    np.testing.assert_allclose(signal.y, expected, atol=1e-7)


def test_attributes_follow_the_spwb_conventions(hdf_path):
    signal, = read_head_hdf(hdf_path)

    assert signal.attributes["Channel Name"] == "Test"
    assert signal.attributes["Channel Unit"] == "Pa"
    assert signal.attributes["X Axis Unit"] == "s"
    assert signal.attributes["Physical Quantity"] == "pressure"
    assert signal.attributes["Description"] == "Test description"
    assert signal.attributes["Start Time"] == "3/6/2010 15:17:00.000"
    assert signal.attributes["Data Source"].endswith("Sine 1kHz.hdf")
    assert signal.attributes["HDF"]["version"] == "4"


def test_calibration_is_metadata_not_a_gain(hdf_path):
    """94 dB is the calibrator level; the samples are already in Pa."""
    signal, = read_head_hdf(hdf_path)

    assert signal.attributes["Calibration"] == "94"
    assert signal.y.max() == pytest.approx(1.0, abs=1e-6)  # not 94


def test_channels_are_interleaved_sample_by_sample(tmp_path):
    """'data org: a1b1 a2b2' - one sample of each channel in turn."""
    left = np.arange(256.0)
    right = -np.arange(256.0)
    path = build_hdf(tmp_path / "stereo.hdf", [
        ("Left", "Pa", "pressure", left),
        ("Right", "Pa", "pressure", right),
    ], n=256)

    a, b = read_head_hdf(path)

    assert (a.name, b.name) == ("Left", "Right")
    np.testing.assert_allclose(a.y, left)
    np.testing.assert_allclose(b.y, right)


def test_t0_comes_from_the_abscissa_first_value(tmp_path):
    path = build_hdf(tmp_path / "offset.hdf",
                     [("Test", "Pa", "pressure", sine())], t0=0.25)

    signal, = read_head_hdf(path)

    assert signal.t0 == pytest.approx(0.25)


def test_contents_lists_channels_without_reading_samples(tmp_path):
    path = build_hdf(tmp_path / "two.hdf", [
        ("Mic", "Pa", "pressure", np.zeros(512)),
        ("Accel", "g", "acceleration", np.zeros(512)),
    ], n=512)

    info = head_hdf_contents(path)

    assert [c.path for c in info] == ["two/Mic", "two/Accel"]
    assert [c.n_samples for c in info] == [512, 512]
    assert [c.y_unit for c in info] == ["Pa", "g"]
    assert [c.quantity for c in info] == ["pressure", "acceleration"]
    assert info[0].duration == pytest.approx(512 * DT)
    assert info[0].is_waveform


def test_selection_by_name_path_and_index(tmp_path):
    path = build_hdf(tmp_path / "two.hdf", [
        ("Mic", "Pa", "pressure", np.ones(64)),
        ("Accel", "g", "acceleration", np.zeros(64)),
    ], n=64)

    assert [s.name for s in read_head_hdf(path, select=["Accel"])] == ["Accel"]
    assert [s.name for s in read_head_hdf(path, select=["two/Mic"])] == ["Mic"]
    assert [s.name for s in read_head_hdf(path, select=[2])] == ["Accel"]
    assert read_head_hdf(path, select=[]) == []


def test_selection_rejects_an_unknown_channel(hdf_path):
    with pytest.raises(KeyError, match="Tacho"):
        read_head_hdf(hdf_path, select=["Tacho"])


def test_decorate_names_appends_the_source_file(hdf_path):
    signal, = read_head_hdf(hdf_path, decorate_names=True)

    assert signal.name == "Test (Sine 1kHz.hdf)"


def test_big_endian_files_decode(tmp_path):
    """'byte order: Motorola' is the other value the format defines."""
    values = sine(n=128)
    path = build_hdf(tmp_path / "motorola.hdf",
                     [("Test", "Pa", "pressure", values)],
                     n=128, byte_order="Motorola")

    signal, = read_head_hdf(path)

    np.testing.assert_allclose(signal.y, values, atol=1e-7)


def test_float64_samples_decode(tmp_path):
    values = sine(n=128)
    path = build_hdf(tmp_path / "f64.hdf",
                     [("Test", "Pa", "pressure", values)],
                     n=128, dtype="FLOAT64")

    signal, = read_head_hdf(path)

    np.testing.assert_allclose(signal.y, values)


# -- the failure messages --------------------------------------------------
def test_a_file_that_is_not_head_hdf_says_so(tmp_path):
    junk = tmp_path / "notes.hdf"
    junk.write_bytes(b"just some text\r\n" * 10)

    with pytest.raises(HeadFormatError, match="start of data"):
        read_head_hdf(junk)


def test_an_hdf5_file_is_not_mistaken_for_this_format(tmp_path):
    """The extensions collide; the error must not be a silent misread."""
    h5 = tmp_path / "confusing.hdf"
    h5.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 512)

    with pytest.raises(HeadFormatError, match="start of data"):
        read_head_hdf(h5)


def test_a_spectrum_file_says_what_to_do_instead(tmp_path):
    path = build_hdf(tmp_path / "spectrum.hdf",
                     [("Test", "Pa", "pressure", sine())],
                     kind="Spectrum data")

    with pytest.raises(HeadFormatError, match="not 'TIME DATA'"):
        read_head_hdf(path)


def test_a_truncated_file_says_so(tmp_path, hdf_path):
    short = tmp_path / "short.hdf"
    short.write_bytes(hdf_path.read_bytes()[:-2048])

    with pytest.raises(HeadFormatError, match="truncated"):
        read_head_hdf(short)


def test_a_header_longer_than_the_file_says_so(tmp_path):
    path = tmp_path / "lying.hdf"
    path.write_bytes(field("start of data", 999999).encode() + b"\r\n")

    with pytest.raises(HeadFormatError, match="only"):
        read_head_hdf(path)


def test_an_unknown_sample_format_names_it(tmp_path, hdf_path):
    raw = hdf_path.read_bytes().replace(b"FLOAT32", b"FLOAT24", 1)
    path = tmp_path / "odd.hdf"
    path.write_bytes(raw)

    with pytest.raises(HeadFormatError, match="FLOAT24"):
        read_head_hdf(path)


def test_an_unknown_channel_layout_is_refused(tmp_path):
    """Better to refuse than to de-interleave a multi-channel file wrongly."""
    path = build_hdf(tmp_path / "blocked.hdf", [
        ("Mic", "Pa", "pressure", np.ones(64)),
        ("Accel", "g", "acceleration", np.zeros(64)),
    ], n=64, data_org="a1a2 b1b2")

    with pytest.raises(HeadFormatError, match="a1b1 a2b2"):
        read_head_hdf(path)


def test_there_is_no_hdf_writer():
    """The port is read-only for HEAD acoustics files; keep it that way."""
    from spwb.processing.io import head_hdf

    assert not [n for n in dir(head_hdf) if n.startswith("write")]


# -- the real recordings ---------------------------------------------------
REAL_FILES = {
    "Sine 1kHz.hdf": dict(name="Test", n=245760, fs=8192.0, unit="Pa",
                          quantity="pressure"),
    "SineSweep 20 to 320Hz.hdf": dict(name="Sine Sweep", n=246784, fs=8192.0,
                                      unit="Pa", quantity="pressure"),
    "Random.hdf": dict(name="Rand", n=245760, fs=8192.0, unit="Pa",
                       quantity="pressure"),
    "Measured - Roof center glass.hdf": dict(name="CNTR GLASS Z", n=60479,
                                             fs=2048.0, unit="g",
                                             quantity="acceleration"),
}


@pytest.mark.parametrize("filename,expected", REAL_FILES.items())
def test_real_artemis_files(filename, expected):
    """Read the ArtemiS recordings the reader was developed against."""
    path = REAL_DIR / filename
    if not path.exists():
        pytest.skip(f"sample recording not available: {path}")

    info, = head_hdf_contents(path)
    signal, = read_head_hdf(path)

    assert signal.name == expected["name"]
    assert signal.n_samples == expected["n"]
    assert signal.fs == pytest.approx(expected["fs"], rel=1e-6)
    assert signal.y_unit == expected["unit"]
    assert info.quantity == expected["quantity"]
    assert np.isfinite(signal.y).all()


def test_the_real_1khz_sine_is_a_1khz_sine():
    """The decisive check: a known signal must come back exactly."""
    path = REAL_DIR / "Sine 1kHz.hdf"
    if not path.exists():
        pytest.skip(f"sample recording not available: {path}")

    signal, = read_head_hdf(path)

    # amplitude 1.0 Pa, so RMS is 1/sqrt(2) - no calibration gain applied
    assert signal.y.max() == pytest.approx(1.0, abs=1e-6)
    assert signal.y.min() == pytest.approx(-1.0, abs=1e-6)
    assert np.sqrt(np.mean(signal.y ** 2)) == pytest.approx(0.5 ** 0.5,
                                                            abs=1e-4)

    # and it really is 1 kHz
    n = 65536
    spectrum = np.abs(np.fft.rfft(signal.y[:n] * np.hanning(n)))
    peak = np.fft.rfftfreq(n, signal.dt)[np.argmax(spectrum)]
    assert peak == pytest.approx(1000.0, abs=1.0)

    # Fit amplitude and phase of a 1 kHz sine to the whole recording. A fitted
    # amplitude of 1.0 to seven figures is only possible if the byte order,
    # sample format and offset are all exactly right.
    amplitude, residual = _fit_1khz(signal.y, signal.dt)
    assert amplitude == pytest.approx(1.0, abs=1e-6)
    assert residual < 1e-3


def test_the_dt_rounding_is_the_only_residual_left():
    """Pin *why* the 1 kHz fit is not perfect, so a real bug cannot hide.

    The header writes ``delta value`` to nine significant figures, so
    ``1/8192`` is stored as ``0.000122070313``. Refitting with the exact
    interval must collapse the residual; if it ever stops doing so, the
    leftover is something else and worth looking at.
    """
    path = REAL_DIR / "Sine 1kHz.hdf"
    if not path.exists():
        pytest.skip(f"sample recording not available: {path}")

    signal, = read_head_hdf(path)
    assert signal.dt == 0.000122070313          # what the file says
    assert signal.dt != 1 / 8192                # what the hardware did

    _, rounded = _fit_1khz(signal.y, signal.dt)
    _, exact = _fit_1khz(signal.y, 1 / 8192)
    assert exact < rounded / 10

    # every decoded value is exactly representable as float32, as it must be
    # if the samples were read as the FLOAT32 the header declares
    assert np.array_equal(signal.y, signal.y.astype(np.float32))


def _fit_1khz(y, dt):
    """Least-squares amplitude of a 1 kHz sine, and the worst residual."""
    t = np.arange(len(y)) * dt
    basis = np.c_[np.sin(2 * np.pi * 1000.0 * t), np.cos(2 * np.pi * 1000.0 * t)]
    coeffs, *_ = np.linalg.lstsq(basis, y, rcond=None)
    return float(np.hypot(*coeffs)), float(np.abs(basis @ coeffs - y).max())


def test_the_real_random_file_is_uniform_noise():
    path = REAL_DIR / "Random.hdf"
    if not path.exists():
        pytest.skip(f"sample recording not available: {path}")

    signal, = read_head_hdf(path)

    # uniform on [-1, 1] has RMS 1/sqrt(3); anything else means a bad decode
    assert np.sqrt(np.mean(signal.y ** 2)) == pytest.approx(1 / np.sqrt(3),
                                                            abs=2e-3)
    assert -1.0 <= signal.y.min() < -0.99
    assert 0.99 < signal.y.max() <= 1.0
