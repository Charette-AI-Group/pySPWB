# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Adaptive Filtering — worked examples
#
# The companion notebook to the [Adaptive Filtering
# manual](../../docs/manuals/adaptive-filtering.md). Same three examples,
# same demo file, same numbers — computed here in a few lines of
# `spwb.processing` instead of clicked in the application.
#
# The manual carries the explanations and the history; this notebook is where
# you change a parameter and watch what happens. Nothing here imports Qt, so
# it runs anywhere `pip install spwb[io]` runs.
#
# ### Three ways to use this, needing progressively more
#
# 1. **Read it.** GitHub renders this file with every graph and number
#    already in place. Nothing to install, nothing to run.
# 2. **Run it as a script** - no Jupyter involved at all:
#    `python examples/manuals/adaptive_filtering.py`
# 3. **Run it cell by cell** in VS Code or Jupyter: change the taps, the
#    step, the filter class, and watch the cancellation succeed or fail.
#
# For (3), VS Code will ask which kernel to use. **Choose the Python
# interpreter you installed SPWB into** - the same one `pip install -e .`
# was run with. There is no separate "spwb" environment unless you created
# one yourself. If it is not offered, run `pip install ipykernel` into it
# and reopen the notebook.
#
# | Section | Shows |
# |---|---|
# | 1 | A tone 4x below the noise, recovered to within 1 % |
# | 2 | Filter length: the cliff at the length of the real path |
# | 3 | Step size, and why "converged" does not mean "worked" |
#
# Every section ends with an `assert` on the numbers the manual quotes.

# %% [markdown]
# ## Setup
#
# The demo datasets are generated rather than committed - they are 21 MB, and
# `spwb.demo` reproduces them exactly from a fixed seed. The cell below
# creates them if they are missing, so there is nothing to download. The
# application offers the same thing under **File > Create Demo Data ...**.

# %%
from pathlib import Path

import numpy as np

try:                                    # notebook: draw figures inline
    get_ipython().run_line_magic("matplotlib", "inline")
except NameError:                       # plain script: draw to a buffer
    import warnings

    import matplotlib
    matplotlib.use("Agg")
    # plt.show() is a no-op under Agg and says so once per figure; the
    # figures are still built, and the notebook build uses the inline
    # backend where they are captured.
    warnings.filterwarnings("ignore", message="FigureCanvasAgg is non-interactive")
import matplotlib.pyplot as plt


def demo_folder() -> Path:
    """Where the demonstration datasets live.

    A git checkout keeps them in its own untracked ``.data/``. Anyone who
    installed the wheel has no checkout and gets them beside wherever they
    are working instead. Either way ``spwb.demo`` writes them on demand.
    """
    here = Path(__file__).resolve() if "__file__" in globals() else Path.cwd()
    for folder in (here, *here.parents):
        if (folder / "pyproject.toml").is_file() and (folder / "src").is_dir():
            return folder / ".data"
    return Path.cwd() / "spwb-demo-data"


DATA = demo_folder()

if not any(DATA.glob("[0-9][0-9]_*.h5")):
    from spwb.demo import write_demo_data

    print(f"creating the demonstration datasets in {DATA} ...")
    write_demo_data(DATA)

print(f"datasets : {len(list(DATA.glob('*.h5')))} files in {DATA}")

# %%
from spwb.processing.dsp import auto_power_spectrums, format_spectrum, signal_statistics
from spwb.processing.dsp.adaptive import LMS_FILTER_CLASSES, lms_filter
from spwb.processing.io import read_hdf5

signals = {s.name: s for s in read_hdf5(DATA / "14_LMS_Noise_cancellation.h5")}
NOISY = "Noisy (tone buried in noise)"
REFERENCE = "Reference (the noise source)"
TRUTH = "Wanted signal (ground truth)"

#: the hidden tone, and where the record has finished adapting
TONE_HZ, TONE_PEAK = 120.0, 0.5
SETTLED = signals[NOISY].n_samples // 2


def tone_amplitude(signal, f0=TONE_HZ):
    """Peak amplitude at the tone, read the way the FFT window would."""
    raw = auto_power_spectrums(signal, freq_resolution=1.0, window="flat_top")
    amp = format_spectrum(raw, function_type="Auto Spectrum - (EU Peak)")
    return float(amp.y[round(f0 / amp.dt)])


def residual(filtered):
    """RMS error against the ground truth, over the settled half."""
    error = np.asarray(filtered.y) - np.asarray(signals[TRUTH].y)
    return float(np.sqrt(np.mean(error[SETTLED:] ** 2)))


def run(*, taps=64, step=0.1, filter_class="Normalized LMS",
        reference=REFERENCE, noisy=NOISY):
    """One adaptive run, with the panel's defaults."""
    return lms_filter(signals[reference], signals[noisy],
                      filter_length=taps, step_size=step,
                      filter_class=filter_class)


print("ready")

# %% [markdown]
# ## 1. Rescuing a buried tone
#
# **File:** `14_LMS_Noise_cancellation.h5` - a 120 Hz tone at 0.5 Pa peak
# buried under noise that reached the microphone through a 31-tap filter.
# The reference is the noise *before* that path; the clean tone is included
# as ground truth so the answer can be checked.
#
# Manual: [Worked example
# 1](../../docs/manuals/adaptive-filtering.md#worked-example-1--rescuing-a-buried-tone).

# %%
print(f"  {'signal':34} {'rms':>9} {'120 Hz peak':>12}")
for name in (NOISY, REFERENCE, TRUTH):
    st = signal_statistics(signals[name])
    peak = tone_amplitude(signals[name]) if name != REFERENCE else float("nan")
    shown = f"{peak:12.5f}" if np.isfinite(peak) else f"{'-':>12}"
    print(f"  {name:34} {st.rms:9.5f} {shown}")

buried = (signal_statistics(signals[NOISY]).rms
          / signal_statistics(signals[TRUTH]).rms)
print(f"\n  the noisy recording is {buried:.2f}x the level of the tone "
      "hidden inside it")

# %%
result = run()

print(f"  level change  : {result.noise_reduction_db:+.2f} dB")
print(f"  convergence   : {result.convergence[-1]:.4f} "
      f"(chance level {result.noise_floor:.4f}) -> "
      f"{'converged' if result.converged else 'still adapting'}")
print(f"  filtered rms  : {signal_statistics(result.filtered).rms:.5f} Pa "
      f"(ground truth {signal_statistics(signals[TRUTH]).rms:.5f})")
print(f"  120 Hz peak   : {tone_amplitude(result.filtered):.5f} "
      f"(ground truth {TONE_PEAK:.5f})")
print(f"  residual      : {residual(result.filtered):.5f} Pa rms over the "
      "settled half")
print(f"\n  outputs: {result.filtered.name!r}")
print(f"           {result.removed.name!r}")

# %% [markdown]
# **The filter did not just cancel the noise - it reconstructed the path.**
# The demo's leak path is a 31-tap FIR scaled by 3.

# %%
from scipy import signal as ss

true_path = ss.firwin(31, 0.25) * 3.0
learned = result.coefficients

print(f"  true path : peak {true_path.max():.5f} at tap "
      f"{int(np.argmax(true_path))}")
print(f"  learned   : peak {np.abs(learned).max():.5f} at tap "
      f"{int(np.argmax(np.abs(learned)))}   ({len(learned)} taps)")
print(f"  agreement on the peak coefficient: "
      f"{100 * np.abs(learned).max() / true_path.max() - 100:+.1f} %")

# %%
fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 6), constrained_layout=True)
window = slice(int(10.0 * signals[NOISY].fs), int(10.05 * signals[NOISY].fs))
top.plot(signals[NOISY].t[window], signals[NOISY].y[window], lw=0.9,
         color="tab:red", alpha=0.8, label="noisy")
top.plot(result.filtered.t[window], result.filtered.y[window], lw=1.6,
         color="tab:blue", label="filtered")
top.plot(signals[TRUTH].t[window], signals[TRUTH].y[window], lw=2.5,
         color="k", alpha=0.3, label="ground truth")
top.set(xlabel="Time (s)", ylabel="Pa",
        title="50 ms after the filter has settled")
top.legend(fontsize=8, loc="upper right")

bottom.plot(result.block_times, result.convergence, marker="o", ms=4, lw=1.2,
            color="tab:green", label="|cross-correlation| with the reference")
bottom.axhline(result.noise_floor, color="grey", ls=":", lw=1,
               label=f"chance level {result.noise_floor:.3f}")
bottom.set(xlabel="Time (s)", ylabel="|x-correlation|",
           title="Convergence: the residual stops tracking the reference")
bottom.legend(fontsize=8)
for ax in (top, bottom):
    ax.grid(True, alpha=0.3)
plt.show()

# %%
assert result.converged
assert result.noise_reduction_db > 11.0, result.noise_reduction_db
assert abs(tone_amplitude(result.filtered) - TONE_PEAK) < 0.02
assert residual(result.filtered) < 0.1
assert abs(np.abs(learned).max() - true_path.max()) < 0.05
print(f"section 1 OK - {result.noise_reduction_db:+.2f} dB, tone recovered at "
      f"{tone_amplitude(result.filtered):.4f} against a true 0.5")

# %% [markdown]
# ## 2. Filter length, the control that decides everything
#
# The interference arrives through a 31-tap filter. A filter with fewer taps
# than that **cannot represent the path**, however long it adapts.
#
# Manual: [Worked example
# 2](../../docs/manuals/adaptive-filtering.md#worked-example-2--filter-length-the-control-that-decides-everything).

# %%
print(f"  {'taps':>6} {'dB':>8} {'converged':>10} {'residual':>10}")
lengths = {}
for taps in (2, 4, 8, 16, 32, 64, 128, 256):
    r = run(taps=taps)
    lengths[taps] = (r.noise_reduction_db, r.converged, residual(r.filtered))
    print(f"  {taps:6d} {r.noise_reduction_db:8.2f} {r.converged!s:>10} "
          f"{residual(r.filtered):10.4f}")

print("\n  the cliff is between 16 and 32 taps - exactly where the filter "
      "becomes\n  long enough to hold the 31-tap impulse response. Below it "
      "the result is\n  worthless; above it, more taps buy almost nothing.")

# %%
fig, ax = plt.subplots(figsize=(9, 4), constrained_layout=True)
taps = sorted(lengths)
ax.semilogx(taps, [lengths[t][0] for t in taps], marker="o", lw=1.5,
            base=2, label="level change (dB)")
ax.axvline(31, color="tab:red", ls="--", lw=1,
           label="the true path is 31 taps long")
ax.axhline(0, color="grey", lw=0.8)
ax.set(xlabel="Filter length (taps)", ylabel="Level change (dB)",
       title="Below the length of the real path, nothing works")
ax.set_xticks(taps)
ax.set_xticklabels([str(t) for t in taps])
ax.grid(True, alpha=0.3)
ax.legend(fontsize=8)
plt.show()

# %%
assert lengths[8][0] < 1.0, "a filter far too short cannot help"
assert lengths[32][0] > 11.0, "32 taps must clear the 31-tap path"
assert lengths[16][0] < lengths[32][0] - 5, "there must be a cliff"
assert lengths[256][2] < lengths[32][2] * 1.2, "more taps must not hurt much"
print(f"section 2 OK - {lengths[16][0]:.2f} dB at 16 taps against "
      f"{lengths[32][0]:.2f} dB at 32")

# %% [markdown]
# ## 3. Step size, and what convergence does not tell you
#
# Manual: [Worked example
# 3](../../docs/manuals/adaptive-filtering.md#worked-example-3--step-size-and-what-convergence-does-not-tell-you).

# %%
print(f"  {'step':>7} {'dB':>8} {'residual':>10}   (accuracy once settled)")
steps = {}
for mu in (0.01, 0.05, 0.1, 0.5, 1.0, 1.5, 1.9):
    r = run(step=mu)
    steps[mu] = (r.noise_reduction_db, residual(r.filtered))
    print(f"  {mu:7g} {r.noise_reduction_db:8.2f} {residual(r.filtered):10.4f}")

print(f"\n  the two columns disagree and both are right: dB peaks at 0.1, but "
      f"the\n  accuracy is {steps[0.1][1] / steps[0.01][1]:.1f}x better at "
      "0.01. A small step converges slowly, so\n  more of the record is spent "
      "adapting and the total level drop is smaller -\n  but once settled it "
      "tracks far more precisely.")

# %% [markdown]
# ### "Converged" means the filter stopped learning, not that it worked

# %%
two_tap = run(taps=2)
print(f"  2 taps: convergence {two_tap.convergence[-1]:.4f} -> "
      f"{'converged' if two_tap.converged else 'still adapting'}, "
      f"level change {two_tap.noise_reduction_db:+.2f} dB")
print("  the filter made the recording WORSE and reported success.\n")
print("  The convergence trace answers one narrow question: does what is left")
print("  still correlate with the reference? With two taps the filter quickly")
print("  extracts everything two taps can explain, then stops improving - so")
print("  the metric is satisfied. It converged to a bad answer.\n")

swapped = run(reference=NOISY, noisy=REFERENCE)
print(f"  roles swapped: {swapped.noise_reduction_db:+.2f} dB  <- a negative "
      "number means\n  the reference does not carry the interference. Check "
      "which signal is which\n  before touching the step size.")

# %% [markdown]
# ### Filter classes, and the step size that is not the same number

# %%
print(f"  {'class':32} {'step':>6} {'dB':>8} {'residual':>10}")
for cls in LMS_FILTER_CLASSES:
    mu = 0.01 if cls == "LMS" else 0.1
    r = run(step=mu, filter_class=cls)
    print(f"  {cls:32} {mu:6g} {r.noise_reduction_db:8.2f} "
          f"{residual(r.filtered):10.4f}")
print("\n  the three normalised entries are the same algorithm - the Noise")
print("  Cancelling names are presets for which signal is wired where.\n")

try:
    run(step=1.0, filter_class="LMS")
except ValueError as exc:
    print("  plain LMS at the normalised default diverges, and says so with "
          "the\n  actual limit for THIS data rather than returning "
          "infinities:\n")
    print(f"    {exc}")

# %%
for bad in (0.0, 2.0, -0.1):
    try:
        run(step=bad)
        raise AssertionError(f"step {bad} should have been refused")
    except ValueError:
        pass
assert steps[0.01][1] < steps[0.1][1], "a small step must be more accurate"
assert steps[1.9][0] < 1.0, "a step near 2 must stop working"
assert two_tap.converged and two_tap.noise_reduction_db < 0
assert swapped.noise_reduction_db < 0
print("section 3 OK - small steps are more accurate, 2 taps 'converges' to "
      f"{two_tap.noise_reduction_db:+.2f} dB, swapped roles give "
      f"{swapped.noise_reduction_db:+.2f} dB")

# %% [markdown]
# ## Where to go next
#
# * The [Adaptive Filtering manual](../../docs/manuals/adaptive-filtering.md)
#   - the same three examples driven through the application, plus the
#   history from Widrow and Hoff's 1960 learning rule to the fetal
#   heartbeat that made the method famous.
# * The other four manuals and their notebooks:
#   [`time_processing.py`](time_processing.py),
#   [`fft_analysis.py`](fft_analysis.py),
#   [`transfer_function.py`](transfer_function.py),
#   [`time_frequency.py`](time_frequency.py).
# * `python tools/verify_demo_data.py` - the assertions that keep the demo
#   datasets honest.
#
# To use your own data, replace `signals` with `read_tdms("run.tdms")` or
# `read_hdf5("measurement.h5")` and pick the two roles. The one thing that
# matters is the reference: correlated with the interference, uncorrelated
# with what you want to keep.
