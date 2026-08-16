"""Capture the screenshots the user manuals use.

Scripted rather than taken by hand, for the reason every hand-made
screenshot eventually fails: the application keeps changing. Re-run this
after a GUI change and every image is current again.

Three details make the output trustworthy, and all three were established
by measurement:

**The real Qt platform, never ``offscreen``.** Qt's offscreen plugin on
Windows has no font database at all - 0 families against 329 for the real
one - so every label renders as a row of empty boxes. Nothing to configure
around; the plugin simply cannot draw text here.

**No window is ever shown.** ``QWidget.grab`` renders the widget into a
pixmap directly, so nothing flashes onto the desktop while this runs, and
the capture still uses real fonts, the real palette and the real DPI.

**The settings store is redirected first.** Otherwise a window restores
whatever geometry, splitter positions and column widths this machine has
saved, and the manual documents one developer's personal layout instead of
what a new user sees.

Usage::

    python tools/make_manual_images.py [names ...]

Images land in ``docs/manuals/images/`` for the manuals to reference, and
are mirrored into ``.screenshots/`` - untracked - for review.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

# Must happen before QApplication exists: the offscreen plugin has no fonts.
os.environ.pop("QT_QPA_PLATFORM", None)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

DATA_DIR = REPO / ".data"
DOCS_DIR = REPO / "docs" / "manuals" / "images"
REVIEW_DIR = REPO / ".screenshots"

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

_app: QApplication | None = None


def session() -> QApplication:
    """A Qt session with the settings store pointed somewhere harmless."""
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
        from spwb.gui import settings
        scratch = QSettings(str(Path(tempfile.mkdtemp()) / "spwb.ini"),
                            QSettings.IniFormat)
        settings._store = lambda: scratch
    return _app


def capture(widget, name: str) -> Path:
    """Render ``widget`` to ``name``.png, without ever showing it."""
    app = session()
    widget.ensurePolished()
    app.processEvents()
    pixmap = widget.grab()          # a real paint, at the real device ratio
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    target = DOCS_DIR / f"{name}.png"
    pixmap.save(str(target))
    shutil.copy2(target, REVIEW_DIR / target.name)
    print(f"   {target.name:44} {pixmap.width()}x{pixmap.height()}")
    return target


def demo(filename: str, *names: str, limit: int | None = None):
    """Signals from one of the datasets tools/make_demo_data.py writes.

    Name the signals wanted rather than slicing: read_hdf5 returns them in
    the file's own (alphabetical) order, not the order they were written,
    so an index quietly selects the wrong trace - which matters when the
    manual quotes the number beside it.
    """
    from spwb.processing.io import read_hdf5

    path = DATA_DIR / filename
    if not path.is_file():
        raise SystemExit(
            f"{path} is missing - run: python tools/make_demo_data.py")
    signals = read_hdf5(path)
    if not names:
        return signals[:limit] if limit else signals
    by_name = {s.name: s for s in signals}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise SystemExit(f"{filename}: no signal named {missing}; "
                         f"it has {sorted(by_name)}")
    return [by_name[n] for n in names]


def time_processing(signals, *, size=(1150, 720)):
    from spwb.gui.bridge import WindowManager
    from spwb.gui.time_processing import TimeProcessingWindow

    session()
    window = TimeProcessingWindow(WindowManager())
    window.resize(*size)
    for signal in signals:
        window.store.add(signal)
    return window


def fft_window(signals, *, size=(1200, 760), **controls):
    from spwb.gui.bridge import WindowManager
    from spwb.gui.fft_analysis import FFTWindow

    session()
    window = FFTWindow(WindowManager())
    window.resize(*size)
    for signal in signals:
        window.store.add(signal)
    for control, value in controls.items():
        getattr(window, control).setCurrentText(value)
    window.recompute()
    return window


# -- the shots --------------------------------------------------------------
def shot_time_processing_overview() -> None:
    """The hub window with a few signals loaded and the plot readable."""
    window = time_processing(demo("01_TimeProcessing_Stats_known_values.h5",
                                  "DC 2.5 V", "Sine 1 Vpk",
                                  "Gaussian noise sigma 1"))
    session().processEvents()
    window.plot.viewbox.setXRange(0.0, 0.06, padding=0)
    capture(window, "time_processing_overview")
    window.close()


def shot_time_processing_stats() -> None:
    """The Stats tab, whose numbers the manual quotes."""
    window = time_processing(demo("01_TimeProcessing_Stats_known_values.h5"))
    window.tabs.setCurrentWidget(window.stats_tab)
    session().processEvents()
    window.plot.viewbox.setXRange(0.0, 0.06, padding=0)
    capture(window, "time_processing_stats_tab")
    window.close()


def shot_fft_known_amplitudes() -> None:
    """Three tones reading 1.00, 0.50 and 0.25 exactly."""
    window = fft_window(demo("04_FFT_Tones_known_amplitudes.h5"),
                        function_type="Auto Spectrum - (EU Peak)")
    session().processEvents()
    window.plot.viewbox.setXRange(0.0, 500.0, padding=0)
    capture(window, "fft_known_amplitudes")
    window.close()


def shot_fft_spl_94db() -> None:
    """1 Pa RMS at 1 kHz displayed as 94.0 dB SPL."""
    window = fft_window(
        demo("06_FFT_SPL_94dB_calibration.h5", "1 Pa RMS at 1 kHz (94 dB)"),
        function_type="Auto Spectrum - (EU RMS)",
        display_option="dB - Sound SPL (ref 20E-6 Pa)")
    session().processEvents()
    window.plot.viewbox.setXRange(0.0, 2000.0, padding=0)
    # the noise floor runs to -200 dB and would squash the peak flat
    window.plot.viewbox.setYRange(0.0, 100.0, padding=0)
    capture(window, "fft_spl_94db")
    window.close()


def shot_about_dialog() -> None:
    from spwb.gui.about import AboutDialog

    session()
    dialog = AboutDialog()
    dialog.resize(520, 240)
    capture(dialog, "about_dialog")
    dialog.close()


SHOTS = {
    "time_processing_overview": shot_time_processing_overview,
    "time_processing_stats_tab": shot_time_processing_stats,
    "fft_known_amplitudes": shot_fft_known_amplitudes,
    "fft_spl_94db": shot_fft_spl_94db,
    "about_dialog": shot_about_dialog,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    wanted = argv[1:] or list(SHOTS)
    unknown = [name for name in wanted if name not in SHOTS]
    if unknown:
        raise SystemExit(f"unknown shot(s) {unknown}; known: {list(SHOTS)}")

    session()
    print(f"capturing to {DOCS_DIR}")
    print(f"   mirrored to {REVIEW_DIR}\n")
    for name in wanted:
        SHOTS[name]()
    print(f"\n{len(wanted)} image(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
