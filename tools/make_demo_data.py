"""Generate demonstration datasets, one per analysis window.

Every signal here is synthetic and *analytically known*, so the point is
not that the plots look plausible - it is that you can check the numbers.
A 1 Pa RMS tone must read 94.0 dB SPL; a 1 V peak sine must read 0.7071 V
RMS; a resonance at 80 Hz must cross -90 degrees of phase there. Where an
expected value is subtler than it looks - a damped peak sits slightly below
fn, coherence dips at a sharp resonance even with no noise - the attribute
says so rather than rounding it off. Each signal carries its result, and the
Time Processing window shows a signal's attributes in the panel under the
list - so the answer is visible next to the measurement.

Usage::

    python tools/make_demo_data.py [output_folder]

Defaults to the DSP Benchmark Signals folder this project has used for its
other reference data. Files are written in SPWB's native HDF5 format, so
they open with File > Open > SPWB / HDF5.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spwb.processing.io import write_hdf5
from spwb.processing.model.signal import Signal

# The repo's own untracked working folder, found relative to this script so
# it follows the checkout. Git ignores .data entirely: everything in it is
# generated from here, so a clean clone simply re-creates it.
DEFAULT_OUT = Path(__file__).resolve().parents[1] / ".data"

FS = 8192.0          # 1 Hz bins with a 8192-point block
FS_AUDIO = 51200.0   # SPWB's default rate, needed to reach 16 kHz
RNG = np.random.default_rng(20260815)


def sig(name, y, fs, unit, note, **extra):
    """A Signal whose attributes say what it is and what to expect."""
    attributes = {"Demo Note": note}
    attributes.update({k: str(v) for k, v in extra.items()})
    return Signal(name=name, y=np.asarray(y, dtype=float), dt=1.0 / fs,
                  y_unit=unit, attributes=attributes)


def t_for(seconds, fs=FS):
    return np.arange(int(seconds * fs)) / fs


# =========================================================================
# Time Processing window
# =========================================================================
def time_processing_stats(out):
    """Stats tab: every statistic has a textbook value."""
    t = t_for(8)
    n = len(t)
    # np.sign is 0 where the sine is exactly 0, which would pull the RMS
    # just under 1.0; force the two-level waveform instead
    square = np.where(np.sin(2 * np.pi * 10 * t) >= 0, 1.0, -1.0)
    signals = [
        sig("DC 2.5 V", np.full(n, 2.5), FS, "V",
            "Constant. Mean 2.5, RMS 2.5, Std 0.",
            Expected_Mean=2.5, Expected_RMS=2.5, Expected_Std=0.0),
        sig("Sine 1 Vpk", np.sin(2 * np.pi * 50 * t), FS, "V",
            "Amplitude 1.0. RMS = 1/sqrt(2), crest factor sqrt(2).",
            Expected_RMS=round(1 / np.sqrt(2), 6), Expected_Mean=0.0,
            Expected_Crest=round(np.sqrt(2), 6)),
        sig("Square 1 Vpk", square, FS, "V",
            "RMS equals the peak, so the crest factor is exactly 1.",
            Expected_RMS=1.0, Expected_Crest=1.0),
        sig("Gaussian noise sigma 1", RNG.standard_normal(n), FS, "V",
            "RMS 1.0, mean 0. For Std / Skewness / Kurtosis use the "
            "TV Metrics tab - the Stats tab reports min, max, RMS and mean.",
            Expected_RMS=1.0, Expected_Mean=0.0,
            Expected_TVMetric_Std=1.0, Expected_TVMetric_Kurtosis=3.0),
        sig("Uniform noise +/-1", RNG.uniform(-1, 1, n), FS, "V",
            "Uniform on [-1, 1]: RMS = 1/sqrt(3) = 0.5774, min -1, max +1.",
            Expected_RMS=round(1 / np.sqrt(3), 6), Expected_Min=-1.0,
            Expected_Max=1.0),
        sig("Sine 1 Vpk + 3 V offset", 3 + np.sin(2 * np.pi * 50 * t), FS, "V",
            "Use Scale Signals > Offset to remove the 3 V DC.",
            Expected_Mean=3.0),
    ]
    return write_hdf5(out / "01_TimeProcessing_Stats_known_values.h5", signals)


def time_processing_tv_metrics(out):
    """TV Metrics tab: sliding-window trends with an obvious shape."""
    t = t_for(10)
    ramp = (t / t[-1])
    burst = np.zeros_like(t)
    for k, start in enumerate((1.0, 3.0, 5.0, 7.0)):
        m = (t >= start) & (t < start + 1.0)
        burst[m] = (k + 1) * 0.25
    signals = [
        sig("Amplitude ramp 0 to 1", ramp * np.sin(2 * np.pi * 60 * t), FS, "V",
            "Running RMS should rise linearly from 0 to 1/sqrt(2).",
            Expected_Final_RMS=round(1 / np.sqrt(2), 6)),
        sig("Four bursts 0.25 to 1.0", burst * np.sin(2 * np.pi * 60 * t),
            FS, "V",
            "Four one-second bursts at 25/50/75/100 %. Running peak "
            "should be a staircase."),
        sig("Steady 0.5 Vpk reference", 0.5 * np.sin(2 * np.pi * 60 * t),
            FS, "V", "Flat reference: every trend should be a straight line.",
            Expected_RMS=round(0.5 / np.sqrt(2), 6)),
    ]
    return write_hdf5(out / "02_TimeProcessing_TVmetrics_trends.h5", signals)


def time_processing_calibration(out):
    """Scale Signals tab: raw volts that need a sensitivity applied."""
    t = t_for(8)
    g_true = 2.0 * np.sin(2 * np.pi * 25 * t)          # 2 g peak
    volts = g_true * 0.100                              # 100 mV/g
    signals = [
        sig("Accel raw", volts, FS, "V",
            "Accelerometer at 100 mV/g. Scale Signals > Calibrate by 10 "
            "(1/0.1) to get g. Result should be 2 g peak.",
            Sensitivity="100 mV/g", Expected_After_Scaling="2.0 g peak"),
        sig("Accel true (for comparison)", g_true, FS, "g",
            "The same signal already in g - compare after calibrating.",
            Expected_Peak=2.0),
    ]
    return write_hdf5(out / "03_TimeProcessing_Calibration_raw_volts.h5",
                      signals)


# =========================================================================
# FFT Analysis window
# =========================================================================
def fft_known_amplitudes(out):
    """Amplitude spectrum reads the tone amplitudes exactly."""
    t = t_for(8)
    y = (1.00 * np.sin(2 * np.pi * 100 * t)
         + 0.50 * np.sin(2 * np.pi * 250 * t)
         + 0.25 * np.sin(2 * np.pi * 400 * t))
    signals = [
        sig("Three tones 1.00 0.50 0.25", y, FS, "V",
            "Tones at 100/250/400 Hz on exact 1 Hz bin centres. With "
            "df = 1 Hz the amplitude spectrum reads 1.00, 0.50, 0.25; the "
            "power spectrum reads half the square of each.",
            Expected_Amplitudes="1.00 / 0.50 / 0.25 V",
            Expected_Power_EU_Peak_Squared="1.0 / 0.25 / 0.0625 V^2",
            Suggested_Settings="df = 1 Hz, hanning, function type Auto Spectrum - (EU Peak)"),
    ]
    return write_hdf5(out / "04_FFT_Tones_known_amplitudes.h5", signals)


def fft_leakage(out):
    """Why the window choice matters: on-bin versus off-bin tones."""
    t = t_for(8)
    signals = [
        sig("Tone on bin 100.0 Hz", np.sin(2 * np.pi * 100.0 * t), FS, "V",
            "Exactly on a 1 Hz bin. Reads 1.00 with any window.",
            Expected_Amplitude=1.0),
        sig("Tone off bin 100.5 Hz", np.sin(2 * np.pi * 100.5 * t), FS, "V",
            "Half a bin off. Hanning under-reads by ~15 %; Flat Top reads "
            "the amplitude correctly. Switch the window to see it "
            "(function type Auto Spectrum - (EU Peak)).",
            Expected_With_flat_top=1.0, Expected_With_hanning="about 0.85"),
        sig("Tone off bin, rectangular worst case",
            np.sin(2 * np.pi * 100.5 * t), FS, "V",
            "Same signal again - compare Rectangular (worst leakage) with "
            "Hanning and Flat Top side by side."),
    ]
    return write_hdf5(out / "05_FFT_Leakage_window_choice.h5", signals)


def fft_spl_calibration(out):
    """The SPL display option, against the 94 dB calibrator standard."""
    t = t_for(8)
    signals = [
        sig("1 Pa RMS at 1 kHz (94 dB)", np.sqrt(2) * np.sin(2 * np.pi * 1000 * t),
            FS, "Pa",
            "1 Pa RMS is the 94 dB SPL calibrator level (re 20 uPa). "
            "Display option 'dB - Sound SPL (ref 20E-6 Pa)' must read "
            "94.0 dB. Use the flat_top window so an off-bin tone still "
            "reads its true level.",
            Expected_SPL="94.0 dB", Expected_RMS="1.0 Pa"),
        sig("0.1 Pa RMS at 1 kHz (74 dB)",
            0.1 * np.sqrt(2) * np.sin(2 * np.pi * 1000 * t), FS, "Pa",
            "Ten times quieter, so exactly 20 dB down.",
            Expected_SPL="74.0 dB"),
        sig("Pink-ish noise 1 Pa RMS", _pink(int(8 * FS)) , FS, "Pa",
            "Broadband at 1 Pa RMS overall - use the Energy Band readout "
            "to sum a band and compare with the total.",
            Expected_Overall="94 dB SPL"),
    ]
    return write_hdf5(out / "06_FFT_SPL_94dB_calibration.h5", signals)


def _pink(n):
    """Pink-ish noise normalised to 1.0 RMS."""
    white = RNG.standard_normal(n)
    spectrum = np.fft.rfft(white)
    f = np.arange(len(spectrum))
    f[0] = 1
    pink = np.fft.irfft(spectrum / np.sqrt(f), n=n)
    return pink / np.sqrt(np.mean(pink ** 2))


def fft_a_weighting(out):
    """Equal tones at octave centres make the A-weighting curve visible."""
    t = t_for(4, FS_AUDIO)
    centres = (31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
    y = sum(np.sin(2 * np.pi * f * t) for f in centres) / 1.0
    signals = [
        sig("Octave tones, equal 1.0 Vpk", y, FS_AUDIO, "Pa",
            "Ten equal tones at octave centres. Unweighted they are all the "
            "same height; switch on A-weighting and the plot becomes the "
            "A-curve itself: -39.4 dB at 31.5 Hz, 0 dB at 1 kHz, "
            "+1.2 dB at 2 kHz, -6.6 dB at 16 kHz.",
            Expected_A_at_1kHz="0 dB (the definition)",
            Expected_A_at_31_5Hz="-39.4 dB",
            Tone_Frequencies=", ".join(str(c) for c in centres)),
    ]
    return write_hdf5(out / "07_FFT_A_weighting_octave_tones.h5", signals)


def fft_harmonics(out):
    """Harmonic distortion with an exactly known THD."""
    t = t_for(8)
    f0 = 100.0
    y = (np.sin(2 * np.pi * f0 * t)
         + 0.10 * np.sin(2 * np.pi * 2 * f0 * t)
         + 0.05 * np.sin(2 * np.pi * 3 * f0 * t)
         + 0.01 * np.sin(2 * np.pi * 4 * f0 * t))
    thd = np.sqrt(0.10 ** 2 + 0.05 ** 2 + 0.01 ** 2) * 100
    signals = [
        sig("100 Hz + harmonics (THD 11.2 %)", y, FS, "V",
            "Fundamental 1.0, harmonics at 10 %, 5 % and 1 %. "
            f"THD = {thd:.2f} %, i.e. {20 * np.log10(thd / 100):.1f} dB "
            "below the fundamental.",
            Expected_THD=f"{thd:.2f} %",
            Expected_Harmonics="H2 -20 dB, H3 -26 dB, H4 -40 dB"),
    ]
    return write_hdf5(out / "08_FFT_Harmonics_THD.h5", signals)


# =========================================================================
# Transfer Function window
# =========================================================================
def _sdof(x, fn, zeta, fs):
    """Pass x through a single-degree-of-freedom resonance."""
    from scipy import signal as ss
    wn = 2 * np.pi * fn
    b, a = ss.bilinear([wn ** 2], [1, 2 * zeta * wn, wn ** 2], fs)
    return ss.lfilter(b, a, x)


def tf_resonance(out):
    """A known resonance the H1 estimate must recover."""
    n = int(20 * FS)
    x = RNG.standard_normal(n)
    fn, zeta = 80.0, 0.05
    y = _sdof(x, fn, zeta, FS)
    q = 1 / (2 * zeta)
    signals = [
        sig("Input (reference)", x, FS, "N",
            "White noise input. Set this as the Reference in the "
            "Transfer Function window.",
            Role="Reference / input"),
        sig("Output (response)", y, FS, "m",
            f"Same noise through a resonance at {fn:g} Hz with "
            f"{zeta * 100:g} % damping (Q = {q:g}). The H1 magnitude peaks "
            f"at 79 Hz, not {fn:g} - a damped resonance peaks at "
            "fn*sqrt(1-2*zeta^2) = 79.8 Hz. The phase crossing IS exactly at "
            f"{fn:g} Hz (-89.9 deg measured), which is why phase is the "
            "reliable way to read a natural frequency. "
            "Coherence is 1.000 across the band - nothing but the input "
            "drives this output - EXCEPT in the few bins at the resonance "
            "itself, where it dips. That dip is bias error, not noise: the "
            "response varies steeply inside one bin. Coarsen the resolution "
            "and watch it get worse (df 1 Hz -> 0.95, 2 Hz -> 0.82, "
            "4 Hz -> 0.61). It is the classic trap when measuring lightly "
            "damped structures.",
            Role="Response / output", Expected_Resonance=f"{fn:g} Hz",
            Expected_Q=f"{q:g}", Expected_Phase_At_Peak="-90 deg",
            Expected_Coherence="1.000 in the band, ~0.95 at the peak at df = 1 Hz"),
    ]
    return write_hdf5(out / "09_TF_SDOF_resonance_H1.h5", signals)


def tf_coherence(out):
    """Coherence below 1 where the output is not caused by the input."""
    n = int(20 * FS)
    x = RNG.standard_normal(n)
    clean = _sdof(x, 80.0, 0.05, FS)
    clean /= np.std(clean)
    contamination = _bandnoise(n, 300.0, 500.0, FS)
    signals = [
        sig("Input (reference)", x, FS, "N",
            "White noise input.", Role="Reference / input"),
        sig("Output with 300-500 Hz interference", clean + 2 * contamination,
            FS, "m",
            "The response plus interference that the input did not cause. "
            "Coherence stays near 1 around the 80 Hz resonance and collapses "
            "between 300 and 500 Hz - which is exactly what coherence is for.",
            Role="Response / output",
            Expected_Coherence="~1 at 80 Hz, far below 1 in 300-500 Hz"),
        sig("Output clean (for comparison)", clean, FS, "m",
            "The same response without interference: coherence ~1 "
            "everywhere. Compare the two.", Role="Response / output"),
    ]
    return write_hdf5(out / "10_TF_Coherence_partial.h5", signals)


def _bandnoise(n, low, high, fs):
    white = RNG.standard_normal(n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1 / fs)
    spectrum[(freqs < low) | (freqs > high)] = 0
    out = np.fft.irfft(spectrum, n=n)
    return out / np.std(out)


def tf_h1_vs_h2(out):
    """The textbook case where H1 and H2 disagree."""
    n = int(20 * FS)
    x = RNG.standard_normal(n)
    y = _sdof(x, 80.0, 0.05, FS)
    y /= np.std(y)
    signals = [
        sig("Input, noisy measurement", x + 0.5 * RNG.standard_normal(n),
            FS, "N",
            "The input as measured, with noise ON THE INPUT. This is the "
            "case H1 gets wrong and H2 gets right.",
            Role="Reference / input"),
        sig("Output, clean measurement", y, FS, "m",
            "Noise-free output. With noise only on the input, H1 "
            "under-estimates the response and H2 is the better estimator. "
            "Switch the estimator and compare - then try file 09, where the "
            "opposite holds.",
            Role="Response / output",
            Expected="H2 closer to the true resonance than H1"),
    ]
    return write_hdf5(out / "11_TF_H1_vs_H2_input_noise.h5", signals)


# =========================================================================
# Time-Frequency window
# =========================================================================
def tfa_chirp(out):
    """A sweep is a straight diagonal on a spectrogram."""
    from scipy import signal as ss
    t = t_for(20)
    up = ss.chirp(t, f0=20, f1=2000, t1=t[-1], method="linear")
    logsweep = ss.chirp(t, f0=20, f1=2000, t1=t[-1], method="logarithmic")
    signals = [
        sig("Linear sweep 20 to 2000 Hz", up, FS, "Pa",
            "A straight diagonal line on the spectrogram. Drag the cursor: "
            "the Frequency Section peak should track the line, and the Time "
            "Section should show one moving peak.",
            Expected="Straight diagonal, 20 Hz at t=0 to 2000 Hz at t=20 s"),
        sig("Logarithmic sweep 20 to 2000 Hz", logsweep, FS, "Pa",
            "The same endpoints, curved instead of straight - the classic "
            "acoustic measurement sweep.",
            Expected="Curved: fast at the start, slow at the end"),
    ]
    return write_hdf5(out / "12_TFA_Sweeps_linear_and_log.h5", signals)


def tfa_bursts(out):
    """Rectangles on the spectrogram, for the cursor cross-sections."""
    t = t_for(16)
    y = np.zeros_like(t)
    plan = ((100.0, 1.0, 4.0), (400.0, 3.0, 7.0),
            (900.0, 6.0, 10.0), (1600.0, 9.0, 14.0))
    for f, start, stop in plan:
        m = (t >= start) & (t < stop)
        y[m] += np.sin(2 * np.pi * f * t[m])
    signals = [
        sig("Four overlapping tone bursts", y, FS, "Pa",
            "Tones at 100/400/900/1600 Hz switching on and off with "
            "overlaps. Each is a rectangle on the spectrogram. Put the "
            "cursor at t=3.5 s and the Time Section should show two peaks "
            "(100 and 400 Hz).",
            Bursts="100 Hz 1-4 s, 400 Hz 3-7 s, 900 Hz 6-10 s, "
                   "1600 Hz 9-14 s"),
    ]
    return write_hdf5(out / "13_TFA_Tone_bursts.h5", signals)


# =========================================================================
# Adaptive Filtering window
# =========================================================================
def lms_noise_cancellation(out):
    """The signal LMS is supposed to rescue."""
    from scipy import signal as ss
    n = int(15 * FS)
    t = np.arange(n) / FS
    wanted = 0.5 * np.sin(2 * np.pi * 120 * t)
    noise = RNG.standard_normal(n)
    # what reaches the microphone is a filtered, delayed version of the noise
    b = ss.firwin(31, 0.25)
    leaked = ss.lfilter(b, [1.0], noise) * 3.0
    signals = [
        sig("Noisy (tone buried in noise)", wanted + leaked, FS, "Pa",
            "A 120 Hz tone at 0.5 Vpk buried under noise about 6x larger. "
            "Set this as the Noisy input.",
            Role="Noisy / primary", Hidden_Tone="120 Hz at 0.5 Vpk"),
        sig("Reference (the noise source)", noise, FS, "Pa",
            "The noise before it was filtered on its way to the microphone. "
            "Set this as the Reference. LMS should learn the path and leave "
            "the 120 Hz tone standing alone - check the result in the FFT "
            "window.",
            Role="Reference / noise", Expected="120 Hz tone recovered at "
            "about 0.5 Vpk once converged"),
        sig("Wanted signal (ground truth)", wanted, FS, "Pa",
            "What the answer should look like. Not an input - it is here so "
            "you can compare.", Role="Ground truth",
            Expected_Amplitude=0.5),
    ]
    return write_hdf5(out / "14_LMS_Noise_cancellation.h5", signals)


README = """SPWB demonstration datasets
===========================

Synthetic signals in SPWB's native HDF5 format, one set per analysis
window. Open with File > Open > SPWB / HDF5 (Ctrl+O).

Every value here is analytically known, so you can check the application
rather than just look at it. Each signal carries its expected result in
its attributes - select a signal in the Time Processing window and the
panel underneath the list shows them.

Regenerate with:  python tools/make_demo_data.py [folder]

TIME PROCESSING WINDOW
  01_TimeProcessing_Stats_known_values.h5
      Stats tab. DC 2.5 V, a 1 Vpk sine (RMS 0.7071), a square wave
      (crest factor exactly 1), Gaussian and uniform noise. Note the
      Stats tab reports min/max/RMS/mean - Std, Skewness and Kurtosis
      are TV Metrics trends.
  02_TimeProcessing_TVmetrics_trends.h5
      TV Metrics tab. A linear amplitude ramp (running RMS is a ramp),
      four bursts at 25/50/75/100 % (running peak is a staircase), and a
      steady reference that should trend flat.
  03_TimeProcessing_Calibration_raw_volts.h5
      Scale Signals tab. Accelerometer output at 100 mV/g; calibrate by
      10 to get g and compare against the true signal in the same file.

FFT ANALYSIS WINDOW
  04_FFT_Tones_known_amplitudes.h5
      Tones at 100/250/400 Hz on exact bin centres. At df = 1 Hz the
      peak spectrum reads 1.00 / 0.50 / 0.25 exactly.
  05_FFT_Leakage_window_choice.h5
      The same tone on a bin and half a bin off. Hanning under-reads the
      off-bin tone by about 15 %; flat_top reads it correctly. This is
      what the window choice is for.
  06_FFT_SPL_94dB_calibration.h5
      1 Pa RMS at 1 kHz is the 94 dB SPL calibrator level. Display
      option 'dB - Sound SPL (ref 20E-6 Pa)' reads 94.0 dB; the 0.1 Pa
      signal reads exactly 20 dB less.
  07_FFT_A_weighting_octave_tones.h5
      Ten equal tones at octave centres, 31.5 Hz to 16 kHz. Switch on
      A-weighting and the plot becomes the A-curve: 0 dB at 1 kHz,
      -39.4 dB at 31.5 Hz, +1.2 dB at 2 kHz.
  08_FFT_Harmonics_THD.h5
      Fundamental plus harmonics at 10 %, 5 % and 1 %, i.e. -20, -26 and
      -40 dB. THD = 11.2 %.

TRANSFER FUNCTION WINDOW
  09_TF_SDOF_resonance_H1.h5
      Noise in, a known 80 Hz resonance out. Magnitude peaks at 79 Hz -
      a damped peak sits at fn*sqrt(1-2*zeta^2) - while the phase
      crossing is exactly at 80 Hz. Coherence is 1.000 across the band
      but dips to ~0.95 at the resonance: bias error, not noise. Coarsen
      df to 2 and 4 Hz and watch the dip deepen to 0.82 and 0.61.
  10_TF_Coherence_partial.h5
      The same response plus interference between 300 and 500 Hz that
      the input did not cause. Coherence collapses to ~0.01 in that band
      and stays high elsewhere. A clean output is included to compare.
  11_TF_H1_vs_H2_input_noise.h5
      Noise on the INPUT. H1 under-estimates and H2 is the better
      estimator - the opposite of the usual case. Switch estimators.

TIME-FREQUENCY WINDOW
  12_TFA_Sweeps_linear_and_log.h5
      20 Hz to 2 kHz over 20 s, linear (a straight diagonal) and
      logarithmic (curved). Drag the cursor and watch both sections.
  13_TFA_Tone_bursts.h5
      Four tones switching on and off with overlaps, so the spectrogram
      is rectangles. At t = 3.5 s the Time Section shows two peaks.

ADAPTIVE FILTERING WINDOW
  14_LMS_Noise_cancellation.h5
      A 120 Hz tone buried under noise about six times larger, plus the
      noise source as a reference. LMS should learn the path and leave
      the tone standing. The clean tone is included as ground truth.
"""


def write_readme(out):
    (out / "README.txt").write_text(README, encoding="utf-8")
    return out / "README.txt"


BUILDERS = (
    ("Time Processing", (time_processing_stats, time_processing_tv_metrics,
                         time_processing_calibration)),
    ("FFT Analysis", (fft_known_amplitudes, fft_leakage, fft_spl_calibration,
                      fft_a_weighting, fft_harmonics)),
    ("Transfer Function", (tf_resonance, tf_coherence, tf_h1_vs_h2)),
    ("Time-Frequency", (tfa_chirp, tfa_bursts)),
    ("Adaptive Filtering", (lms_noise_cancellation,)),
)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    out = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    print(f"writing demo datasets to {out}\n")
    written = []
    for window, builders in BUILDERS:
        print(f"{window}:")
        for build in builders:
            path = build(out)
            size = path.stat().st_size / 1024
            print(f"   {path.name:52} {size:7.0f} KB")
            written.append(path)
    readme = write_readme(out)
    print(f"\n   {readme.name:52} {readme.stat().st_size / 1024:7.1f} KB")
    print(f"\n{len(written)} data files + README written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
