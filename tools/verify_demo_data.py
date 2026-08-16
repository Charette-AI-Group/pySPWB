"""Check every claim the demo datasets make, using SPWB's own DSP.

The files written by make_demo_data.py state expected values in their
attributes. This re-reads them and confirms the application actually
produces those numbers, so the demo data cannot quietly start teaching
something untrue.

    python tools/make_demo_data.py && python tools/verify_demo_data.py
"""
import pathlib

import numpy as np

from spwb.processing.dsp import (
    auto_power_spectrums,
    format_spectrum,
    signal_statistics,
    transfer_function,
)
from spwb.processing.io import read_hdf5

D = pathlib.Path(__file__).resolve().parents[1] / ".data"
ok = fail = 0


def check(label, got, want, tol):
    global ok, fail
    good = abs(got - want) <= tol
    ok, fail = ok + good, fail + (not good)
    print(f"  [{'OK ' if good else 'FAIL'}] {label:52} got {got:11.5f}  want {want:.5f}")


def by_name(sigs):
    return {s.name: s for s in sigs}


print("01 Stats -------------------------------------------------------")
s = by_name(read_hdf5(D / "01_TimeProcessing_Stats_known_values.h5"))
st = signal_statistics(s["DC 2.5 V"]);            check("DC mean", st.mean, 2.5, 1e-9)
check("DC rms", st.rms, 2.5, 1e-9)
st = signal_statistics(s["Sine 1 Vpk"]);          check("sine rms", st.rms, 2**-0.5, 1e-4)
st = signal_statistics(s["Square 1 Vpk"]);        check("square rms", st.rms, 1.0, 1e-9)
st = signal_statistics(s["Gaussian noise sigma 1"]); check("gauss rms", st.rms, 1.0, 0.02)
st = signal_statistics(s["Uniform noise +/-1"]);  check("uniform rms", st.rms, 3**-0.5, 0.01)

print("04 FFT amplitudes ----------------------------------------------")
sig = read_hdf5(D / "04_FFT_Tones_known_amplitudes.h5")[0]
sp = auto_power_spectrums(sig, freq_resolution=1.0, window="hanning")
amp = format_spectrum(sp, function_type="Auto Spectrum - (EU Peak)")
for f, want in ((100, 1.0), (250, 0.5), (400, 0.25)):
    check(f"amplitude at {f} Hz", float(amp.y[round(f / amp.dt)]), want, 0.01)

print("05 Leakage -----------------------------------------------------")
s = by_name(read_hdf5(D / "05_FFT_Leakage_window_choice.h5"))
for name, win, want, tol in (("Tone on bin 100.0 Hz", "hanning", 1.0, 0.01),
                             ("Tone off bin 100.5 Hz", "hanning", 0.85, 0.06),
                             ("Tone off bin 100.5 Hz", "flat_top", 1.0, 0.02)):
    sp = auto_power_spectrums(s[name], freq_resolution=1.0, window=win)
    a = format_spectrum(sp, function_type="Auto Spectrum - (EU Peak)")
    check(f"{name[:22]} + {win}", float(a.y.max()), want, tol)

print("06 SPL ---------------------------------------------------------")
s = by_name(read_hdf5(D / "06_FFT_SPL_94dB_calibration.h5"))
for name, want in (("1 Pa RMS at 1 kHz (94 dB)", 94.0),
                   ("0.1 Pa RMS at 1 kHz (74 dB)", 74.0)):
    sp = auto_power_spectrums(s[name], freq_resolution=1.0, window="flat_top")
    db = format_spectrum(sp, function_type="Auto Spectrum - (EU RMS)",
                         display_option="dB - Sound SPL (ref 20E-6 Pa)")
    check(f"SPL {name[:26]}", float(db.y.max()), want, 0.15)

print("07 A-weighting -------------------------------------------------")
sig = read_hdf5(D / "07_FFT_A_weighting_octave_tones.h5")[0]
sp = auto_power_spectrums(sig, freq_resolution=2.0, window="flat_top")
plain = format_spectrum(sp, function_type="Auto Spectrum - (EU RMS)",
                        display_option="dB - NO reference value")
weighted = format_spectrum(sp, function_type="Auto Spectrum - (EU RMS)",
                           display_option="dB - NO reference value", weighting="A-weighting")
for f, want in ((1000, 0.0), (31.5, -39.4), (2000, 1.2), (8000, -1.1)):
    k = round(f / plain.dt)
    check(f"A-weight delta at {f} Hz", float(weighted.y[k] - plain.y[k]), want, 0.6)

print("08 Harmonics ---------------------------------------------------")
sig = read_hdf5(D / "08_FFT_Harmonics_THD.h5")[0]
sp = auto_power_spectrums(sig, freq_resolution=1.0, window="hanning")
amp = format_spectrum(sp, function_type="Auto Spectrum - (EU Peak)")
base = float(amp.y[round(100 / amp.dt)])
for mult, want_db in ((2, -20.0), (3, -26.0), (4, -40.0)):
    got = 20 * np.log10(float(amp.y[round(100 * mult / amp.dt)]) / base)
    check(f"harmonic {mult} rel. level (dB)", got, want_db, 0.6)

print("09 Transfer function -------------------------------------------")
s = by_name(read_hdf5(D / "09_TF_SDOF_resonance_H1.h5"))
tf, coh = transfer_function(s["Input (reference)"], s["Output (response)"],
                            freq_resolution=1.0, overlap=0.5, estimator="H1")
H = tf.attributes["TF_Complex"]
peak = int(np.argmax(np.abs(H)))
f9 = np.arange(len(coh.y)) * coh.dt
# the file documents: magnitude peaks at 79 Hz (fn*sqrt(1-2z^2)=79.8), the
# -90 deg phase crossing is exactly at fn, coherence is 1.000 in the band
# and dips to ~0.95 at the resonance through bias error
check("magnitude peak (Hz)", peak * tf.dt, 79.0, 0.6)
check("phase at 80 Hz (deg)", float(np.degrees(np.angle(H[80]))), -90.0, 1.0)
check("median coherence in band", float(np.median(coh.y[(f9>20)&(f9<1000)])), 1.0, 0.005)
check("coherence dip at resonance", float(coh.y[peak]), 0.95, 0.03)

print("10 Coherence ---------------------------------------------------")
s = by_name(read_hdf5(D / "10_TF_Coherence_partial.h5"))
_tf, coh = transfer_function(s["Input (reference)"],
                             s["Output with 300-500 Hz interference"],
                             freq_resolution=2.0, overlap=0.5, estimator="H1")
f = np.arange(len(coh.y)) * coh.dt
check("coherence away from interference", float(np.median(coh.y[(f>600)&(f<1500)])), 1.0, 0.02)
band = (f > 320) & (f < 480)
check("mean coherence 320-480 Hz", float(coh.y[band].mean()), 0.25, 0.25)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
