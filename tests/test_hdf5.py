"""The SPWB HDF5 format.

Two things are being protected here. The obvious one is a faithful round
trip. The less obvious one is that the files stay readable by tools that
are not SPWB - the whole reason for choosing HDF5 over TDMS - so the tests
also open the files with bare h5py and assert the layout and the string
encoding the format document promises.
"""
import json

import numpy as np
import pytest

from spwb import Signal
from spwb.processing.io import hdf5 as H

h5py = pytest.importorskip("h5py")

FS = 1000.0
DT = 1.0 / FS


def sine(name="sine", amp=1.0, f=50.0, n=1000, unit="Pa"):
    t = np.arange(n) * DT
    return Signal(name, amp * np.sin(2 * np.pi * f * t), DT, y_unit=unit)


# -- round trip --------------------------------------------------------------
def test_round_trip_preserves_everything(tmp_path):
    original = sine("Accel X", amp=9.81, unit="m/s^2")
    original.attributes["Calibration"] = 9.81
    original.attributes["Operator"] = "FC"
    out = H.write_hdf5(tmp_path / "run.h5", [original])

    (back,) = H.read_hdf5(out)
    assert back.name == original.name
    np.testing.assert_array_equal(back.y, original.y)
    assert back.dt == pytest.approx(original.dt)
    assert back.t0 == pytest.approx(original.t0)
    assert back.y_unit == "m/s^2"
    assert back.x_unit == original.x_unit
    assert back.attributes["Calibration"] == pytest.approx(9.81)
    assert back.attributes["Operator"] == "FC"


def test_t0_and_odd_units_survive(tmp_path):
    s = Signal("odd", np.arange(10.0), 0.25, t0=12.5, y_unit="m/s²",
               x_unit="sec")
    out = H.write_hdf5(tmp_path / "odd.h5", [s])
    (back,) = H.read_hdf5(out)
    assert back.t0 == pytest.approx(12.5)
    assert back.y_unit == "m/s²"          # non-ASCII round trips
    assert back.x_unit == "sec"


def test_many_signals_and_groups(tmp_path):
    a = sine("a")
    b = sine("b")
    b.attributes["TDMS Group"] = "Run 2"
    out = H.write_hdf5(tmp_path / "multi.h5", [a, b])
    back = {s.name: s for s in H.read_hdf5(out)}
    assert set(back) == {"a", "b"}
    assert back["a"].attributes["HDF5 Group"] == "SPWB"
    assert back["b"].attributes["HDF5 Group"] == "Run 2"


def test_group_override(tmp_path):
    out = H.write_hdf5(tmp_path / "g.h5", [sine("a")], group="Test 7")
    with h5py.File(out) as f:
        assert list(f) == ["Test 7"]


def test_extension_is_added_when_missing(tmp_path):
    out = H.write_hdf5(tmp_path / "noext", [sine()])
    assert out.suffix == ".h5"
    assert out.exists()


# -- the format document's promises ------------------------------------------
def test_root_attributes_identify_the_format(tmp_path):
    out = H.write_hdf5(tmp_path / "x.h5", [sine()])
    with h5py.File(out) as f:
        assert f.attrs["spwb_format"].decode() == H.FORMAT_NAME
        assert f.attrs["spwb_format_version"].decode() == H.FORMAT_VERSION
        assert f.attrs["created"].decode().endswith("Z")


def test_strings_are_fixed_length_not_variable_length(tmp_path):
    """Variable-length strings are h5py's default and trip older MATLAB."""
    out = H.write_hdf5(tmp_path / "s.h5", [sine(unit="Pa")])
    with h5py.File(out) as f:
        dataset = f["SPWB"]["sine"]
        for key in ("name", "unit", "x_unit"):
            dtype = dataset.attrs.get_id(key).dtype
            assert dtype.kind == "S", f"{key} is {dtype}, not fixed-length"
        assert f.attrs.get_id("spwb_format").dtype.kind == "S"


def test_numeric_attributes_are_native_not_strings(tmp_path):
    out = H.write_hdf5(tmp_path / "n.h5", [sine()])
    with h5py.File(out) as f:
        dataset = f["SPWB"]["sine"]
        assert dataset.attrs.get_id("dt").dtype.kind == "f"
        assert dataset.attrs.get_id("t0").dtype.kind == "f"


def test_a_stranger_can_read_it_with_five_lines_of_h5py(tmp_path):
    """The documented snippet must actually work."""
    H.write_hdf5(tmp_path / "run.h5", [sine("Accel X", amp=3.0, unit="Pa")])
    with h5py.File(tmp_path / "run.h5") as f:
        dataset = f["SPWB"]["Accel X"]
        y = dataset[:]
        fs = 1.0 / dataset.attrs["dt"]
        unit = dataset.attrs["unit"].decode()
    assert len(y) == 1000
    assert fs == pytest.approx(FS)
    assert unit == "Pa"
    assert np.abs(y).max() == pytest.approx(3.0, rel=1e-3)


def test_datasets_are_one_dimensional_float64(tmp_path):
    out = H.write_hdf5(tmp_path / "d.h5", [sine()])
    with h5py.File(out) as f:
        dataset = f["SPWB"]["sine"]
        assert dataset.ndim == 1
        assert dataset.dtype == np.float64


# -- naming ------------------------------------------------------------------
def test_a_slash_in_a_name_does_not_become_a_subgroup(tmp_path):
    s = sine("Left/Right")
    out = H.write_hdf5(tmp_path / "slash.h5", [s])
    with h5py.File(out) as f:
        keys = list(f["SPWB"])
        assert len(keys) == 1
        assert "/" not in keys[0]
    (back,) = H.read_hdf5(out)
    assert back.name == "Left/Right"          # the true name is restored


def test_duplicate_names_get_distinct_keys_but_keep_their_name(tmp_path):
    out = H.write_hdf5(tmp_path / "dup.h5", [sine("mic"), sine("mic"),
                                             sine("mic")])
    with h5py.File(out) as f:
        assert sorted(f["SPWB"]) == ["mic", "mic #2", "mic #3"]
    back = H.read_hdf5(out)
    assert [s.name for s in back] == ["mic", "mic", "mic"]


def test_an_empty_name_still_writes(tmp_path):
    out = H.write_hdf5(tmp_path / "empty.h5", [sine("")])
    with h5py.File(out) as f:
        assert list(f["SPWB"]) == ["signal"]


# -- attributes --------------------------------------------------------------
def test_nested_attributes_are_json_encoded_and_restored(tmp_path):
    s = sine()
    s.attributes["TDMS"] = {"wf_increment": 0.001, "nested": {"a": [1, 2]}}
    out = H.write_hdf5(tmp_path / "j.h5", [s])
    with h5py.File(out) as f:
        names = [n.decode() for n in f["SPWB"]["sine"].attrs["_spwb_json_attrs"]]
        assert names == ["TDMS"]
        assert json.loads(f["SPWB"]["sine"].attrs["TDMS"].decode())["nested"]
    (back,) = H.read_hdf5(out)
    assert back.attributes["TDMS"]["wf_increment"] == 0.001
    assert back.attributes["TDMS"]["nested"]["a"] == [1, 2]


def test_a_complex_array_attribute_stays_native(tmp_path):
    """Transfer functions carry TF_Complex; HDF5 stores complex directly."""
    s = sine()
    s.attributes["TF_Complex"] = np.array([1 + 2j, 3 - 4j])
    out = H.write_hdf5(tmp_path / "c.h5", [s])
    with h5py.File(out) as f:
        assert f["SPWB"]["sine"].attrs.get_id("TF_Complex").dtype.kind == "c"
    (back,) = H.read_hdf5(out)
    np.testing.assert_allclose(back.attributes["TF_Complex"], [1 + 2j, 3 - 4j])


def test_an_unrepresentable_attribute_is_skipped_not_fatal(tmp_path):
    """Skipped, not stringified: "<function ... at 0x7f...>" is a memory
    address pretending to be data, and it would survive into the file."""
    s = sine()
    s.attributes["callback"] = lambda x: x        # cannot be stored at all
    s.attributes["Keep"] = "this"
    out = H.write_hdf5(tmp_path / "bad.h5", [s])   # must not raise
    with h5py.File(out) as f:
        skipped = [n.decode() for n in
                   f["SPWB"]["sine"].attrs["_spwb_skipped_attrs"]]
    assert skipped == ["callback"]
    (back,) = H.read_hdf5(out)
    assert back.attributes["Keep"] == "this"
    assert "callback" not in back.attributes


def test_dates_are_kept_as_iso_strings(tmp_path):
    """TDMS files carry a wf_start_time; a date is worth preserving."""
    import datetime as dt

    s = sine()
    s.attributes["Start Time"] = dt.datetime(2026, 8, 13, 4, 15, 0)
    s.attributes["Nested"] = {"when": dt.date(2026, 1, 1)}
    out = H.write_hdf5(tmp_path / "dates.h5", [s])
    (back,) = H.read_hdf5(out)
    assert back.attributes["Start Time"].startswith("2026-08-13T04:15")
    assert back.attributes["Nested"]["when"] == "2026-01-01"


def test_reserved_attributes_are_not_duplicated(tmp_path):
    out = H.write_hdf5(tmp_path / "r.h5", [sine()])
    (back,) = H.read_hdf5(out)
    for reserved in ("name", "dt", "t0", "unit", "x_unit"):
        assert reserved not in back.attributes


def test_provenance_is_recorded_on_read(tmp_path):
    out = H.write_hdf5(tmp_path / "p.h5", [sine("mic")])
    (back,) = H.read_hdf5(out)
    assert back.attributes["Data Source"].endswith("p.h5")
    assert back.attributes["Channel Name"] == "mic"


# -- selection and listing ---------------------------------------------------
def test_contents_lists_without_importing(tmp_path):
    out = H.write_hdf5(tmp_path / "l.h5", [sine("a", unit="V"),
                                           sine("b", n=500)])
    info = {c.name: c for c in H.hdf5_contents(out)}
    assert set(info) == {"a", "b"}
    assert info["a"].unit == "V"
    assert info["a"].fs == pytest.approx(FS)
    assert info["b"].n_samples == 500
    assert info["b"].duration == pytest.approx(0.5)
    assert info["a"].path == "SPWB/a"


@pytest.mark.parametrize("selector", ["SPWB/b", "b"])
def test_select_by_path_or_name(tmp_path, selector):
    out = H.write_hdf5(tmp_path / "s.h5", [sine("a"), sine("b")])
    picked = H.read_hdf5(out, select=[selector])
    assert [s.name for s in picked] == ["b"]


def test_selecting_nothing_returns_nothing(tmp_path):
    out = H.write_hdf5(tmp_path / "s.h5", [sine("a")])
    assert H.read_hdf5(out, select=[]) == []


def test_unknown_selection_raises(tmp_path):
    out = H.write_hdf5(tmp_path / "s.h5", [sine("a")])
    with pytest.raises(KeyError, match="Nope"):
        H.read_hdf5(out, select=["Nope"])


def test_decorate_names_appends_the_file(tmp_path):
    out = H.write_hdf5(tmp_path / "run.h5", [sine("mic")])
    (back,) = H.read_hdf5(out, decorate_names=True)
    assert back.name == "mic (run.h5)"


# -- atomic writes -----------------------------------------------------------
def test_a_failed_write_leaves_the_previous_file_intact(tmp_path,
                                                        monkeypatch):
    target = tmp_path / "keep.h5"
    H.write_hdf5(target, [sine("original")])
    before = target.read_bytes()

    def explode(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(H.os, "replace", explode)
    with pytest.raises(RuntimeError, match="disk full"):
        H.write_hdf5(target, [sine("replacement")])

    assert target.read_bytes() == before          # untouched
    (back,) = H.read_hdf5(target)
    assert back.name == "original"
    # and no debris left behind
    assert [p.name for p in tmp_path.iterdir()] == ["keep.h5"]


def test_no_temporary_file_survives_a_successful_write(tmp_path):
    H.write_hdf5(tmp_path / "clean.h5", [sine()])
    assert [p.name for p in tmp_path.iterdir()] == ["clean.h5"]


# -- compression -------------------------------------------------------------
def test_compression_is_on_by_default_and_shrinks_the_file(tmp_path):
    # a smooth signal compresses well; random data would not
    quiet = Signal("flat", np.zeros(200_000), DT)
    packed = H.write_hdf5(tmp_path / "packed.h5", [quiet])
    plain = H.write_hdf5(tmp_path / "plain.h5", [quiet], compression=None)
    assert packed.stat().st_size < plain.stat().st_size / 10
    with h5py.File(packed) as f:
        assert f["SPWB"]["flat"].compression == "gzip"


def test_compressed_data_is_still_exact(tmp_path):
    rng = np.random.default_rng(0)
    s = Signal("noise", rng.standard_normal(5000), DT)
    out = H.write_hdf5(tmp_path / "z.h5", [s])
    (back,) = H.read_hdf5(out)
    np.testing.assert_array_equal(back.y, s.y)     # gzip is lossless


def test_compression_can_be_disabled(tmp_path):
    out = H.write_hdf5(tmp_path / "u.h5", [sine()], compression=None)
    with h5py.File(out) as f:
        assert f["SPWB"]["sine"].compression is None


# -- validation --------------------------------------------------------------
def test_writing_nothing_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="no signals"):
        H.write_hdf5(tmp_path / "x.h5", [])


def test_a_foreign_hdf5_file_is_reported_clearly(tmp_path):
    path = tmp_path / "foreign.h5"
    with h5py.File(path, "w") as f:
        f.create_group("stuff").create_dataset("thing", data=np.arange(10.0))
    with pytest.raises(ValueError, match="not an SPWB HDF5 signal"):
        H.read_hdf5(path)


def test_creates_missing_directories(tmp_path):
    out = H.write_hdf5(tmp_path / "deep" / "nested" / "run.h5", [sine()])
    assert out.exists()


# -- interop with the other formats ------------------------------------------
def test_tdms_to_hdf5_keeps_group_and_attributes(tmp_path):
    pytest.importorskip("nptdms")
    from spwb.processing.io import read_tdms, write_tdms

    source = sine("Accel X", unit="m/s^2")
    source.attributes["TDMS Group"] = "Run 1"
    tdms_path = write_tdms(tmp_path / "in.tdms", [source])
    (from_tdms,) = read_tdms(tdms_path)

    h5_path = H.write_hdf5(tmp_path / "out.h5", [from_tdms])
    (back,) = H.read_hdf5(h5_path)

    assert back.attributes["HDF5 Group"] == "Run 1"
    assert back.y_unit == "m/s^2"
    np.testing.assert_allclose(back.y, from_tdms.y)
    assert back.attributes["Channel Unit"] == "m/s^2"


def test_a_spectrum_survives_the_round_trip(tmp_path):
    """Analysis results carry rich attributes; none of it should be lost."""
    from spwb.processing.dsp import auto_power_spectrums

    spectrum = auto_power_spectrums(sine(amp=3.0), freq_resolution=2.0,
                                    window="hanning")
    out = H.write_hdf5(tmp_path / "spec.h5", [spectrum])
    (back,) = H.read_hdf5(out)
    assert back.x_unit == "Hz"
    assert back.attributes["FFT_Window_Type"] == "hanning"
    assert back.attributes["FFT_Nb_Averages"] == \
        spectrum.attributes["FFT_Nb_Averages"]
    assert back.attributes["FFT_EQ_Noise_BW"] == pytest.approx(1.5)
    np.testing.assert_allclose(back.y, spectrum.y)
