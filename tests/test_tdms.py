"""TDMS mapping layer: NI waveform properties <-> Signal.

Byte-level parsing is nptdms' job; these tests cover the SPWB conventions
(attribute keys, naming, selection, timing fallbacks) and a full
write -> read round trip.
"""
import numpy as np
import pytest

from spwb import Signal, SignalStore
from spwb.processing.dsp import spectral as S
from spwb.processing.io import (
    append_source_to_name,
    read_tdms,
    tdms_contents,
    write_tdms,
)

nptdms = pytest.importorskip("nptdms")


@pytest.fixture
def tdms_path(tmp_path):
    """A LabVIEW-style TDMS: two waveform channels + one bare channel."""
    from nptdms import ChannelObject, TdmsWriter

    dt = 1.0 / 2048.0
    t = np.arange(2048) * dt
    accel = ChannelObject("Run 1", "Accel  X", 9.81 * np.sin(2 * np.pi * 50 * t),
                          properties={
                              "wf_increment": dt,
                              "wf_start_offset": 0.25,
                              "wf_samples": 2048,
                              "wf_xunit_string": "s",
                              "wf_xname": "Time",
                              "NI_UnitDescription": "m/s^2",
                          })
    mic = ChannelObject("Run 1", "Mic", 0.5 * np.cos(2 * np.pi * 120 * t),
                        properties={
                            "wf_increment": dt,
                            "wf_samples": 2048,
                            "unit_string": "Pa",
                        })
    tach = ChannelObject("Aux", "Tacho", np.arange(64, dtype=float))  # no timing
    path = tmp_path / "run.tdms"
    with TdmsWriter(str(path)) as w:
        w.write_segment([accel, mic, tach])
    return path


def test_contents_lists_every_channel(tdms_path):
    info = {c.path: c for c in tdms_contents(tdms_path)}
    assert set(info) == {"Run 1/Accel  X", "Run 1/Mic", "Aux/Tacho"}
    accel = info["Run 1/Accel  X"]
    assert accel.is_waveform and accel.n_samples == 2048
    assert accel.dt == pytest.approx(1 / 2048)
    assert accel.duration == pytest.approx(1.0)
    assert accel.y_unit == "m/s^2"
    assert info["Aux/Tacho"].is_waveform is False
    assert info["Aux/Tacho"].dt is None


def test_read_maps_waveform_properties(tdms_path):
    sigs = {s.name: s for s in read_tdms(tdms_path, select=["Run 1/Accel  X"])}
    s = sigs["Accel X"]                     # double space collapsed
    assert s.n_samples == 2048
    assert s.fs == pytest.approx(2048.0)
    assert s.t0 == pytest.approx(0.25)      # wf_start_offset honoured
    assert s.t[0] == pytest.approx(0.25)
    assert s.y_unit == "m/s^2"
    assert s.x_unit == "s"
    assert s.attributes["Channel Name"] == "Accel X"
    assert s.attributes["Channel Unit"] == "m/s^2"
    assert s.attributes["X Axis Unit"] == "s"
    assert s.attributes["TDMS Group"] == "Run 1"
    assert s.attributes["Data Source"].endswith("run.tdms")
    assert s.attributes["TDMS"]["wf_samples"] == 2048  # raw props preserved


def test_read_accepts_unit_string_alias(tdms_path):
    (mic,) = read_tdms(tdms_path, select=["Mic"])   # bare channel name works
    assert mic.y_unit == "Pa"
    assert mic.t0 == 0.0


def test_read_all_skips_nothing_and_needs_dt_for_bare_channels(tdms_path):
    with pytest.raises(ValueError, match="wf_increment"):
        read_tdms(tdms_path)
    sigs = read_tdms(tdms_path, dt=1e-3)
    assert len(sigs) == 3
    tacho = next(s for s in sigs if s.name == "Tacho")
    assert tacho.dt == pytest.approx(1e-3)


def test_unknown_channel_raises(tdms_path):
    with pytest.raises(KeyError, match="Nope"):
        read_tdms(tdms_path, select=["Nope"])


def test_decorate_names_matches_labview_convention(tdms_path):
    (s,) = read_tdms(tdms_path, select=["Mic"], decorate_names=True)
    assert s.name == "Mic (run.tdms)"
    assert s.attributes["Channel Name"] == "Mic (run.tdms)"


def test_append_source_falls_back_to_unknown():
    s = Signal("raw", np.zeros(4), 1.0)
    assert append_source_to_name(s).name == "raw (unknown)"


def test_round_trip_preserves_signal(tmp_path, tdms_path):
    original = read_tdms(tdms_path, select=["Run 1/Accel  X", "Mic"])
    out = write_tdms(tmp_path / "rt.tdms", original)
    back = {s.name: s for s in read_tdms(out)}
    assert set(back) == {"Accel X", "Mic"}
    for s in original:
        r = back[s.name]
        np.testing.assert_allclose(r.y, s.y, rtol=0, atol=0)
        assert r.dt == pytest.approx(s.dt)
        assert r.t0 == pytest.approx(s.t0)
        assert r.y_unit == s.y_unit
        assert r.x_unit == s.x_unit
        assert r.attributes["TDMS Group"] == s.attributes["TDMS Group"]


def test_end_to_end_load_share_and_analyse(tdms_path):
    """The vertical slice: file -> store -> spectrum, with attributes intact."""
    store = SignalStore()
    seen = []
    store.subscribe(lambda ev, sig: seen.append((ev, sig.name)))

    for sig in read_tdms(tdms_path, select=["Run 1/Accel  X"]):
        store.add(sig)
    assert seen == [("added", "Accel X")]

    accel = next(iter(store))
    spec = S.auto_power_spectrums(accel, freq_resolution=2.0, window="hanning")
    k = int(round(50.0 / spec.dt))
    assert spec.y[k] == pytest.approx(9.81 ** 2 / 2, rel=1e-3)
    assert spec.x_unit == "Hz"
    assert spec.attributes["Data Source"].endswith("run.tdms")  # provenance kept
    assert spec.attributes["FFT_Window_Type"] == "hanning"
