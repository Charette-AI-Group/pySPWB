# Bundled resources

Files the application loads at runtime. Paths come from
[`spwb/app_config.py`](../app_config.py) — never build one by hand, because
a PyInstaller build reads them from the extraction directory rather than
from the source tree, and `app_config` is what knows the difference.

Anything in this folder ships in the wheel — `pyproject.toml` includes
`spwb/resources/*` as package data.

## Icons

All generated, following the approach CloakClip uses for its own.
**Do not edit the files** — edit the drawing and re-run it:

```bash
python tools/make_icons.py          # all of them, or name the ones you want
```

| File | Used for | Found through |
|---|---|---|
| `spwb.ico` | The application, Windows and Linux | `app_config.icon_file()` |
| `spwb.png` | The application, macOS — 1024×1024 | `app_config.icon_file()` |
| `window-tdp.ico` | Time Processing | `app_config.window_icon_file("tdp")` |
| `window-fft.ico` | FFT Analysis | `... ("fft")` |
| `window-tf.ico` | Transfer Function | `... ("tf")` |
| `window-tfa.ico` | Time-Frequency | `... ("tfa")` |
| `window-lms.ico` | Adaptive Filtering | `... ("lms")` |

Every `.ico` carries **16, 24, 32, 48, 64, 128 and 256 px**, each one
*drawn* at that size rather than shrunk from the largest: below about 24 px
a scaled-down rendering loses its strokes and turns to mush, so the
generator thickens lines and drops detail as it goes down.

Each window's artwork says what that window shows — a waveform, a spectrum,
a resonance curve, a spectrogram over its two cross-sections, noise
resolving into a clean tone. They share one blue background so they read as
a family; **the application itself is gold**, so on a taskbar holding one
SPWB and several of its own windows, the one to click is the odd-coloured
tile.

If a file is missing the application runs without that icon rather than
failing: `icon_file()` and `window_icon_file()` both return `None`, and
`gui/icons.apply_window_icon` does nothing. `tests/test_gui_icons.py` checks
that each file exists, carries every size, differs from the others, and is
actually worn by its window.
