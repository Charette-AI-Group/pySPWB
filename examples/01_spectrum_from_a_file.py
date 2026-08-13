"""Load a recording and compute a spectrum - the notebook workflow.

Nothing here touches Qt: `pip install spwb[io]` is enough. Run it as a
script, or paste the cells into a notebook.

    python examples/01_spectrum_from_a_file.py
"""
import matplotlib.pyplot as plt
import numpy as np

from spwb import Signal
from spwb.processing.dsp import auto_power_spectrums, band_rms, format_spectrum
from spwb.processing.io import write_tdms

# --- 1. get a signal ------------------------------------------------------
# Normally: signals = read_tdms("run.tdms")
# Here we synthesise one so the example runs anywhere.
fs = 8192.0
dt = 1.0 / fs
t = np.arange(int(4 * fs)) * dt
rng = np.random.default_rng(0)
accel = Signal(
    name="Accel X",
    y=(9.81 * np.sin(2 * np.pi * 120 * t)
       + 3.0 * np.sin(2 * np.pi * 355 * t)
       + 0.5 * rng.standard_normal(len(t))),
    dt=dt,
    y_unit="m/s^2",
)
print(accel)

# --- 2. averaged auto power spectrum --------------------------------------
# Same parameters the FFT window exposes: resolution, overlap, window.
spectrum = auto_power_spectrums(accel, freq_resolution=1.0, overlap=0.5,
                                window="hanning")
print(f"{spectrum.attributes['FFT_Nb_Averages']} averages, "
      f"df = {spectrum.dt:g} Hz, ENBW = "
      f"{spectrum.attributes['FFT_EQ_Noise_BW']:.4f} bins")

# The raw spectrum is in EU_rms^2. Scale it for display the way the
# application's Spectral Function Type / Spectrum Display Options do.
rms = format_spectrum(spectrum, function_type="Auto Spectrum - (EU RMS)")
peak = rms.y.max()
print(f"peak {peak:.4f} {rms.y_unit}  "
      f"(expected {9.81 / np.sqrt(2):.4f} for a 9.81 m/s^2 sine)")

# --- 3. band levels -------------------------------------------------------
for lo, hi in [(100, 140), (300, 400), (0, fs / 2)]:
    print(f"  {lo:4g}-{hi:<6g} Hz : "
          f"{band_rms(spectrum, lo, hi):8.4f} m/s^2 rms")

# --- 4. plot --------------------------------------------------------------
fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 6), constrained_layout=True)
top.plot(accel.t[:2000], accel.y[:2000], lw=0.6)
top.set(xlabel="Time (s)", ylabel=f"Amplitude ({accel.y_unit})",
        title=accel.name)
bottom.semilogy(rms.t, rms.y, lw=0.8)
bottom.set(xlabel="Frequency (Hz)", ylabel=rms.y_unit, xlim=(0, 1000))
bottom.grid(True, which="both", alpha=0.3)
plt.savefig("example_01.png", dpi=110)
print("wrote example_01.png")

# --- 5. save, for the application or for anyone else ----------------------
write_tdms("example_01.tdms", [accel])
print("wrote example_01.tdms")
