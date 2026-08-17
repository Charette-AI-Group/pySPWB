# Examples

Everything here uses only `spwb.processing` — no Qt, no GUI.

```bash
pip install spwb[io] matplotlib
python examples/01_spectrum_from_a_file.py
python examples/02_transfer_function_and_spectrogram.py
```

## Quickstarts

| | |
|---|---|
| [`01_spectrum_from_a_file.py`](01_spectrum_from_a_file.py) | Load a recording, average an auto power spectrum, scale it for display, read band levels, save back to TDMS. |
| [`02_transfer_function_and_spectrogram.py`](02_transfer_function_and_spectrogram.py) | H1 frequency response with coherence on a 3-mode structure, then a spectrogram of a run-up with the dominant frequency tracked. |

They synthesise their own signals so they run anywhere. To use your own
data, replace the synthesis with:

```python
from spwb.processing.io import read_tdms, read_wave

signals = read_tdms("run.tdms")          # or read_wave("take1.wav")
```

## `manuals/` — companions to the user manuals

One per analysis window, working the same examples as the corresponding
[user manual](../docs/manuals/) but in code, on the demonstration datasets.
They create the datasets on first run via `spwb.demo`, so they work from a
plain `pip install spwb[io]` as well as from a checkout — no clone needed,
nothing to download.

| | |
|---|---|
| [`manuals/time_processing.py`](manuals/time_processing.py) | The hub window: statistics against textbook values, sensitivity and calibration, normalisation, sliding-window trends. → [rendered notebook](../docs/manuals/notebooks/time-processing.ipynb) · [manual](../docs/manuals/time-processing.md) |
| [`manuals/fft_analysis.py`](manuals/fft_analysis.py) | Spectra: amplitude accuracy, leakage and window choice, dB and SPL, A-weighting, THD and energy bands. → [rendered notebook](../docs/manuals/notebooks/fft-analysis.ipynb) · [manual](../docs/manuals/fft-analysis.md) |

### Using one

**Reading** a notebook needs nothing at all — GitHub renders
`docs/manuals/notebooks/*.ipynb` complete with graphs and output.

**Running** one as a script needs nothing but matplotlib:

```bash
python examples/manuals/fft_analysis.py
```

**Running it interactively**, which is the point of the notebook form, needs
a Jupyter kernel. Open the `.ipynb` in VS Code or Jupyter and select **the
Python interpreter SPWB is installed in** — the one you ran `pip install
-e .` with. There is no separate `spwb` environment unless you made one;
installing into your everyday Python is perfectly normal, and that
interpreter is the one to pick. If it does not appear in the list:

```bash
pip install ipykernel
```

into that interpreter, then reopen the notebook. To have it show up under a
name you recognise rather than a bare version number:

```bash
python -m ipykernel install --user --name pyspwb --display-name "pySPWB"
```

### Editing one

These are written in **jupytext percent format**: they are plain Python
that runs with `python`, and VS Code, PyCharm and Jupyter open them
directly as notebooks. The `.ipynb` files committed under
`docs/manuals/notebooks/` are generated from them —

```bash
pip install -e .[docs]
python tools/make_example_notebooks.py
```

— so edit the `.py`, never the `.ipynb`.

Each section asserts the numbers its manual quotes, which is why
`tests/test_examples.py` runs these scripts: if the library drifts from
the documentation, the suite fails rather than the manual quietly becoming
wrong.
