# Examples

Both scripts use only `spwb.processing` — no Qt, no GUI. They run as
scripts or paste straight into a notebook.

```bash
pip install spwb[io] matplotlib
python examples/01_spectrum_from_a_file.py
python examples/02_transfer_function_and_spectrogram.py
```

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
