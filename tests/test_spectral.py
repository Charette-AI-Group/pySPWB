"""Spectra vs LabVIEW 2022 + analytical sanity checks."""
import numpy as np
import pytest

from spwb import Signal
from spwb.processing.dsp import spectral as S

SIGNALS = ["sine_bin", "sine_offbin", "noise", "multitone"]


@pytest.mark.parametrize("sname", SIGNALS)
def test_aps_matches_labview(lv, sname):
    x = lv[f"sig_{sname}"]
    dt = float(lv["dt"])
    s, df = S.auto_power_spectrum(x, dt)
    ref = lv[f"aps_{sname}"]
    assert len(s) == len(ref)
    assert df == pytest.approx(float(lv["df"]), rel=1e-12)
    np.testing.assert_allclose(s, ref, rtol=1e-7, atol=1e-14)


@pytest.mark.parametrize("wname", ["hanning", "flat_top", "kaiser"])
def test_windowed_aps_chain_matches_labview(lv, wname):
    wx = lv[f"win_{wname}_wx"]
    dt = float(lv["dt"])
    s, _ = S.auto_power_spectrum(wx, dt)
    np.testing.assert_allclose(s, lv[f"winaps_{wname}"], rtol=1e-7, atol=1e-14)


# -- analytical checks -------------------------------------------------------
def test_sine_power_at_bin(lv):
    """A 2.0-peak sine at an exact bin must read A^2/2 = 2.0 EU rms^2."""
    s, df = S.auto_power_spectrum(lv["sig_sine_bin"], float(lv["dt"]))
    k = int(round(128.0 / df))
    assert s[k] == pytest.approx(2.0, rel=1e-9)


def test_parseval(lv):
    x = lv["sig_noise"]
    s, _ = S.auto_power_spectrum(x, float(lv["dt"]))
    # sum of single-sided power (plus Nyquist term dropped by NI) ~ mean square
    nyq = (np.abs(np.fft.rfft(x))[-1] / len(x)) ** 2
    assert s.sum() + nyq == pytest.approx(np.mean(x ** 2), rel=1e-9)


def test_averaged_spectrum_windowed_sine(lv):
    """Full SPWB chain: averaging + window + last-bin copy + attributes."""
    dt = float(lv["dt"])
    n = int(lv["N"])
    t = np.arange(8 * n) * dt
    sig = Signal("sine", 2.0 * np.sin(2 * np.pi * 128.0 * t), dt, y_unit="Pa")
    out = S.auto_power_spectrums(sig, freq_resolution=1.0, overlap=0.5,
                                 window="hanning")
    assert out.n_samples == n // 2 + 1          # 0 Hz .. Fs/2 inclusive
    assert out.y[-1] == out.y[-2]               # last-bin copy
    assert out.attributes["FFT_Nb_Averages"] == 15  # (8N - N)/(N/2) + 1
    assert out.attributes["FFT_Window_Type"] == "hanning"
    assert out.attributes["FFT_EQ_Noise_BW"] == pytest.approx(1.5)
    k = int(round(128.0 / out.dt))
    assert out.y[k] == pytest.approx(2.0, rel=1e-6)  # amplitude preserved
    assert out.x_unit == "Hz"


def test_scale_spectrum_options():
    s = np.array([0.0, 2.0, 0.5])
    df, enbw = 1.0, 1.5
    rms, _ = S.scale_spectrum(s, df, form="rms")
    np.testing.assert_allclose(rms, np.sqrt(s))
    peak, _ = S.scale_spectrum(s, df, form="peak")
    np.testing.assert_allclose(peak, np.sqrt(2 * s))
    psd, _ = S.scale_spectrum(s, df, form="power", density=True,
                              eq_noise_bw=enbw)
    np.testing.assert_allclose(psd, s / (enbw * df))
    db, _ = S.scale_spectrum(s, df, form="power", db=True, db_reference="spl")
    assert db[1] == pytest.approx(10 * np.log10(2.0 / (20e-6) ** 2))
    assert np.isinf(db[0])  # log of 0 -> -inf, no crash


def test_store_pubsub():
    from spwb import SignalStore
    store = SignalStore()
    events = []
    unsub = store.subscribe(lambda ev, sig: events.append((ev, sig.name)))
    a = store.add(Signal("a", np.zeros(4), 1.0))
    store.update(a.with_(name="a2"))
    store.remove(a.sid)
    assert events == [("added", "a"), ("updated", "a2"), ("removed", "a2")]
    unsub()
    store.add(Signal("b", np.zeros(4), 1.0))
    assert len(events) == 3 and len(store) == 1
