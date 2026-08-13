"""Frequency response, coherence and a spectrogram - still no GUI.

    python examples/02_transfer_function_and_spectrogram.py
"""
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import lfilter

from spwb import Signal
from spwb.processing.dsp import (
    format_transfer_function,
    stft_spectrogram,
    transfer_function,
)

fs = 2048.0
dt = 1.0 / fs
n = 1 << 16
rng = np.random.default_rng(11)

# --- a 3-mode structure driven by broadband noise -------------------------
force = rng.standard_normal(n)


def mode(x, f0, zeta, gain):
    w = 2 * np.pi * f0 * dt
    r = np.exp(-zeta * w)
    return lfilter([gain * (1 - r) ** 2], [1.0, -2 * r * np.cos(w), r ** 2], x)


response = (mode(force, 60.0, 0.02, 40.0)
            + mode(force, 210.0, 0.015, 25.0)
            + mode(force, 540.0, 0.03, 12.0))
response += 0.02 * response.std() * rng.standard_normal(n)

reference = Signal("Force", force, dt, y_unit="N")
output = Signal("Accel", response, dt, y_unit="m/s^2")

# --- frequency response ---------------------------------------------------
tf, coherence = transfer_function(reference, output, freq_resolution=1.0,
                                  overlap=0.5, estimator="H1")
print(f"{tf.name}: {tf.attributes['FFT_Nb_Averages']} averages, "
      f"unit {tf.y_unit}")

H = np.asarray(tf.attributes["TF_Complex"])     # complex FRF for curve fitting
phase = format_transfer_function(tf, "Phase Unwrap (Degree)")

band = (tf.t >= 20) & (tf.t <= 800)
print(f"mean coherence 20-800 Hz: {coherence.y[band].mean():.4f}")

# the three modes, found as local maxima of |H|
interior = tf.y[1:-1]
peaks = np.where((interior > tf.y[:-2]) & (interior > tf.y[2:]))[0] + 1
strongest = sorted(peaks[np.argsort(tf.y[peaks])][-3:])
print("resonances:", [f"{tf.t[i]:.1f} Hz" for i in strongest])

fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True,
                         constrained_layout=True)
axes[0].semilogy(tf.t, tf.y, lw=0.8)
axes[0].set(ylabel=f"|H| ({tf.y_unit})", title=tf.name)
axes[1].plot(phase.t, phase.y, lw=0.8, color="tab:orange")
axes[1].set(ylabel="Phase (deg)")
axes[2].plot(coherence.t, coherence.y, lw=0.8, color="tab:green")
axes[2].set(ylabel="Coherence", xlabel="Frequency (Hz)", ylim=(0, 1.05),
            xlim=(0, 900))
for ax in axes:
    ax.grid(True, which="both", alpha=0.3)
plt.savefig("example_02_tf.png", dpi=110)
print("wrote example_02_tf.png")

# --- spectrogram of a run-up ----------------------------------------------
duration = 6.0
t = np.arange(int(duration * fs)) * dt
sweep = 2 * np.pi * np.cumsum(40 + (280 / duration) * t) * dt
runup = Signal("Run-up",
               np.sin(sweep) + 0.5 * np.sin(2 * sweep)
               + 0.05 * rng.standard_normal(len(t)),
               dt, y_unit="Pa")

spec = stft_spectrogram(runup, block_size=512).to_db(dynamic_range=70)
print(f"spectrogram {spec.shape} (time x frequency), "
      f"df = {spec.df:g} Hz, dt = {spec.dt * 1e3:g} ms")

# the dominant frequency over time - order tracking in three lines
ridge = spec.freqs[spec.data.argmax(axis=1)]
print(f"ridge: {ridge[2]:.0f} Hz -> {ridge[-3]:.0f} Hz")

fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
mesh = ax.pcolormesh(spec.times, spec.freqs, spec.data.T, shading="nearest",
                     cmap="inferno")
ax.plot(spec.times, ridge, "c--", lw=1, label="dominant frequency")
ax.set(xlabel="Time (s)", ylabel="Frequency (Hz)", ylim=(0, 1200),
       title=runup.name)
ax.legend(loc="upper left")
fig.colorbar(mesh, ax=ax, label="dB re peak")
plt.savefig("example_02_spectrogram.png", dpi=110)
print("wrote example_02_spectrogram.png")
