# pySPWB user manuals

One manual per analysis window. Each works through demonstration files
from `.data/` whose expected values are checked by
`tools/verify_demo_data.py`, so every number quoted in a manual is one the
application actually produces — not one derived on paper and hoped for.

| Manual | Window | Demo files | Companion notebook |
|---|---|---|---|
| [Time Processing](time-processing.md) | The hub: files, statistics, calibration, trends | 01–03 | [notebook](notebooks/time-processing.ipynb) |
| [FFT Analysis](fft-analysis.md) | Spectra, windows, dB, weighting, energy bands | 04–08 | [notebook](notebooks/fft-analysis.ipynb) |
| Transfer Function | *(to be written)* | 09–11 | |
| Time-Frequency Analysis | *(to be written)* | 12–13 | |
| Adaptive Filtering (LMS) | *(to be written)* | 14 | |

Each manual drives the application; each notebook works the same examples
in code, one section per example. GitHub renders the notebooks with their
output and graphs, so a reader needs nothing installed to read one.

Also see [`../hdf5-format.md`](../hdf5-format.md) for the native file
format.

## Working on these

**The shape each manual follows**, established by
[FFT Analysis](fft-analysis.md):

1. **What the window is for** — in the language of the question a user
   arrives with, not the language of the algorithm.
2. **Where this comes from** — half a page of history. Who worked it out,
   when, and what problem they were actually trying to solve. It costs a
   page and it is the difference between a control panel and an
   explanation; a reader who knows *why* the window functions exist picks
   the right one without a rule of thumb.
3. **Opening the window** — including the menu path and shortcut.
4. **A tour of the controls** — one screenshot of the defaults, then every
   control with its default and what it does.
5. **Worked examples**, one per demo file, in increasing difficulty. Each
   names the file, lists the settings to change, shows the result, and
   quotes the numbers.
6. **The maths, and how it is pinned to LabVIEW** — the computation chain
   with the originating VI for each step, plus any deliberate deviation.
7. **Tips and traps** — the things that make a user think the software is
   wrong when it is not.
8. **The same analysis in a notebook** — the Qt-free equivalent, because
   half the audience never opens the GUI.
9. **Reference tables** — the enum values, verbatim, with units.

**The companion notebook** lives in `examples/manuals/<window>.py` in
jupytext percent format — plain Python, so it diffs like code and runs with
`python` — and is executed into `notebooks/<window>.ipynb` by:

```bash
pip install -e .[docs]
python tools/make_example_notebooks.py
```

Edit the `.py`, never the `.ipynb`. The builder assigns cell ids by
position and discards execution timings, so rebuilding an unchanged example
produces byte-identical output and a rebuild is not a diff. Every section
of a notebook ends with `assert`s on the numbers its manual quotes, and
`tests/test_examples.py` runs the scripts — with matplotlib alone, no
Jupyter — so documentation drift fails the suite.

**The images are generated, never taken by hand:**

```bash
python tools/make_manual_images.py
```

They land in `images/` and are mirrored to `.screenshots/` (untracked) for
review. Re-run it after any GUI change and every manual is current again.
The script's docstring explains the three rules that make its output
trustworthy — a real Qt platform, no window ever shown, and the settings
store redirected first. Do not "simplify" any of the three away; each was
established by measurement, and each fails silently rather than loudly.

**Before quoting a number in a manual, produce it.** Run it through
`spwb.processing` and paste what comes out, to the digits the application
shows. If a value cannot be verified, say so in the text rather than
rounding it into looking verified.
