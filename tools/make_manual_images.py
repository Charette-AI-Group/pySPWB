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

from PySide6.QtCore import QSettings, Qt
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


def fft_window(signals, *, size=(1200, 760), window_type=None, df=None,
               **controls):
    """An FFT window with signals loaded and its combo boxes set.

    ``controls`` names combo-box attributes and the text to select, so a
    shot reads like the sequence of clicks the manual asks for. ``df`` and
    ``window_type`` are separate because neither is a plain combo box: the
    resolution is a spin box, and the window list stores its SPWB key as
    item data while displaying a prettier label.
    """
    from spwb.gui.bridge import WindowManager
    from spwb.gui.fft_analysis import FFTWindow

    session()
    window = FFTWindow(WindowManager())
    window.resize(*size)
    for signal in signals:
        window.store.add(signal)
    if df is not None:
        window.freq_resolution.setValue(df)
    if window_type is not None:
        index = window.window_box.findData(window_type)
        if index < 0:
            raise SystemExit(f"no window named {window_type!r}")
        window.window_box.setCurrentIndex(index)
    for control, value in controls.items():
        box = getattr(window, control)
        if box.findText(value) < 0:
            raise SystemExit(f"{control}: no option {value!r}; "
                             f"has {[box.itemText(i) for i in range(box.count())]}")
        box.setCurrentText(value)
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


def select_signal(window, name: str) -> None:
    """Select a signal in the list by name, as a click on its row would.

    By name rather than by row: read_hdf5 returns signals in the file's own
    alphabetical order, so a row index quietly selects a different one.
    """
    for i in range(window.tree.topLevelItemCount()):
        item = window.tree.topLevelItem(i)
        if item.data(0, Qt.UserRole).name == name:
            window.tree.setCurrentItem(item)
            return
    raise SystemExit(f"no signal named {name!r} in the window")


def tf_window(signals, *, references=(), size=(1220, 780), df=None,
              window_type=None, **controls):
    """A Transfer Function window with roles assigned and controls set.

    ``references`` names the signals to mark as Reference; everything else
    becomes a Response. Assigning by name rather than relying on the
    window's "first signal becomes the reference" default keeps a shot
    correct even if read_hdf5's alphabetical order changes.
    """
    from spwb.gui.bridge import WindowManager
    from spwb.gui.tf_analysis import TransferFunctionWindow

    session()
    window = TransferFunctionWindow(WindowManager())
    window.resize(*size)
    for signal in signals:
        window.store.add(signal)

    names = {s.name for s in window.store}
    missing = [n for n in references if n not in names]
    if missing:
        raise SystemExit(f"no signal named {missing}; window has {sorted(names)}")
    for signal in window.store:
        window._roles[signal.sid] = ("Reference" if signal.name in references
                                     else "Response")

    if df is not None:
        window.freq_resolution.setValue(df)
    if window_type is not None:
        index = window.window_box.findData(window_type)
        if index < 0:
            raise SystemExit(f"no window named {window_type!r}")
        window.window_box.setCurrentIndex(index)
    for control, value in controls.items():
        box = getattr(window, control)
        if box.findText(value) < 0:
            raise SystemExit(f"{control}: no option {value!r}; has "
                             f"{[box.itemText(i) for i in range(box.count())]}")
        box.setCurrentText(value)
    window.recompute()
    return window


def shot_tf_overview() -> None:
    """The window as it opens on the SDOF resonance: magnitude, log axes."""
    window = tf_window(demo("09_TF_SDOF_resonance_H1.h5"),
                       references=("Input (reference)",),
                       log_x="Logarithmic", log_y="Logarithmic")
    session().processEvents()
    capture(window, "tf_overview")
    window.close()


def shot_tf_phase_crossing() -> None:
    """Phase passes -90 deg exactly at the natural frequency."""
    window = tf_window(demo("09_TF_SDOF_resonance_H1.h5"),
                       references=("Input (reference)",),
                       display_type="Phase (Degree)")
    session().processEvents()
    window.plot.viewbox.setXRange(60.0, 100.0, padding=0)
    window.plot.viewbox.setYRange(-180.0, 10.0, padding=0)
    capture(window, "tf_phase_crossing")
    window.close()


def shot_tf_coherence_interference() -> None:
    """Coherence collapses only where the input did not cause the output."""
    window = tf_window(
        demo("10_TF_Coherence_partial.h5"),
        references=("Input (reference)",),
        df=2.0, display_type="Coherence")
    session().processEvents()
    window.plot.viewbox.setXRange(0.0, 1500.0, padding=0)
    capture(window, "tf_coherence_interference")
    window.close()


def _estimator_shot(estimator: str, name: str) -> None:
    """Demo 11 - noise on the input - under one estimator."""
    window = tf_window(demo("11_TF_H1_vs_H2_input_noise.h5"),
                       references=("Input, noisy measurement",),
                       estimator=estimator)
    session().processEvents()
    window.plot.viewbox.setXRange(40.0, 130.0, padding=0)
    window.plot.viewbox.setYRange(0.0, 20.0, padding=0)
    capture(window, name)
    window.close()


def shot_tf_estimator_h1() -> None:
    _estimator_shot("H1", "tf_estimator_h1")


def shot_tf_estimator_h2() -> None:
    _estimator_shot("H2", "tf_estimator_h2")


def tfa_window(signals, *, channel=None, size=(1280, 830), block=None,
               overlap=None, cursor=None, window_type=None, **controls):
    """A Time-Frequency window with one channel selected and a cursor set.

    ``channel`` names the signal to analyse - this window shows one at a
    time - and ``cursor`` is a ``(time_s, frequency_hz)`` pair placed on the
    cross-hair, which is what drives the two section plots.
    """
    from spwb.gui.bridge import WindowManager
    from spwb.gui.tfa_analysis import TimeFrequencyWindow

    session()
    window = TimeFrequencyWindow(WindowManager())
    window.resize(*size)
    for signal in signals:
        window.store.add(signal)

    if channel is not None:
        index = window.channel.findText(channel)
        if index < 0:
            raise SystemExit(
                f"no channel {channel!r}; window has "
                f"{[window.channel.itemText(i) for i in range(window.channel.count())]}")
        window.channel.setCurrentIndex(index)
    if block is not None:
        window.block_size.setCurrentText(str(block))
    if overlap is not None:
        window.overlap.setValue(overlap)
    if window_type is not None:
        index = window.window_box.findData(window_type)
        if index < 0:
            raise SystemExit(f"no window named {window_type!r}")
        window.window_box.setCurrentIndex(index)
    for control, value in controls.items():
        getattr(window, control).setCurrentText(value)

    window.recompute()
    if cursor is not None:
        window.v_line.setValue(float(cursor[0]))
        window.h_line.setValue(float(cursor[1]))
    return window


def shot_tfa_overview() -> None:
    """A linear sweep is a straight diagonal - the window's defining picture."""
    window = tfa_window(demo("12_TFA_Sweeps_linear_and_log.h5"),
                        channel="Linear sweep 20 to 2000 Hz",
                        cursor=(10.0, 1008.0))
    session().processEvents()
    window.image_plot.viewbox.setYRange(0.0, 2500.0, padding=0)
    capture(window, "tfa_overview")
    window.close()


def shot_tfa_log_sweep() -> None:
    """The same endpoints, curved: equal time per octave."""
    window = tfa_window(demo("12_TFA_Sweeps_linear_and_log.h5"),
                        channel="Logarithmic sweep 20 to 2000 Hz",
                        cursor=(10.0, 200.0))
    session().processEvents()
    window.image_plot.viewbox.setYRange(0.0, 2500.0, padding=0)
    capture(window, "tfa_log_sweep")
    window.close()


def shot_tfa_bursts_cursor() -> None:
    """The headline check: at t = 3.5 s the Time Section shows two peaks."""
    window = tfa_window(demo("13_TFA_Tone_bursts.h5"),
                        cursor=(3.5, 400.0))
    session().processEvents()
    window.image_plot.viewbox.setYRange(0.0, 2000.0, padding=0)
    window.time_section_plot.viewbox.setXRange(0.0, 2000.0, padding=0)
    capture(window, "tfa_bursts_cursor")
    window.close()


def shot_tfa_block_size() -> None:
    """The longest block: fine in frequency, smeared in time."""
    window = tfa_window(demo("12_TFA_Sweeps_linear_and_log.h5"),
                        channel="Linear sweep 20 to 2000 Hz",
                        block=8192, cursor=(10.0, 1008.0))
    session().processEvents()
    window.image_plot.viewbox.setYRange(0.0, 2500.0, padding=0)
    capture(window, "tfa_block_size")
    window.close()


def shot_time_processing_attributes() -> None:
    """A selected signal, with the attributes panel stating its answer."""
    window = time_processing(demo("01_TimeProcessing_Stats_known_values.h5"))
    session().processEvents()
    select_signal(window, "Sine 1 Vpk")
    session().processEvents()
    window.plot.viewbox.setXRange(0.0, 0.06, padding=0)
    capture(window, "time_processing_attributes")
    window.close()


def shot_time_processing_scale_tab() -> None:
    """The Scale Signals tab with a 100 mV/g calibration staged."""
    window = time_processing(
        demo("03_TimeProcessing_Calibration_raw_volts.h5"))
    window.tabs.setCurrentWidget(window.scale_tab)
    session().processEvents()

    # stage what the manual asks for, without pressing Apply: the point of
    # the shot is the edited row, and the tab stages rather than applying
    table = window.scale_tab.table
    for row in range(table.rowCount()):
        if table.item(row, 0).text() == "Accel raw":
            table.item(row, 1).setText("g")       # Unit
            table.item(row, 2).setText("10")      # Calib Factor = 1 / 0.100
            break
    else:
        raise SystemExit("no 'Accel raw' row in the Scale Signals table")

    session().processEvents()
    window.plot.viewbox.setXRange(0.0, 0.2, padding=0)
    capture(window, "time_processing_scale_tab")
    window.close()


def shot_time_processing_tvm_tab() -> None:
    """The peak trend of the four bursts: a staircase over the data."""
    window = time_processing(demo("02_TimeProcessing_TVmetrics_trends.h5",
                                  "Four bursts 0.25 to 1.0"))
    window.tabs.setCurrentWidget(window.tvm_tab)
    window.tvm_tab.trend.setCurrentText("Absolute Peak")
    session().processEvents()
    window.tvm_tab.compute()          # adds the trend to the window
    session().processEvents()
    capture(window, "time_processing_tvm_tab")
    window.close()


def shot_fft_overview() -> None:
    """The window exactly as it opens: defaults, nothing touched yet."""
    window = fft_window(demo("04_FFT_Tones_known_amplitudes.h5"))
    session().processEvents()
    window.plot.viewbox.setXRange(0.0, 500.0, padding=0)
    capture(window, "fft_overview")
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


def _leakage(window_type: str, name: str) -> None:
    """One tone on a bin and one half a bin off, under a given window."""
    window = fft_window(
        demo("05_FFT_Leakage_window_choice.h5",
             "Tone on bin 100.0 Hz", "Tone off bin 100.5 Hz"),
        window_type=window_type,
        function_type="Auto Spectrum - (EU Peak)")
    session().processEvents()
    # tight enough that the two peak heights can be compared by eye
    window.plot.viewbox.setXRange(96.0, 104.0, padding=0)
    window.plot.viewbox.setYRange(0.0, 1.1, padding=0)
    capture(window, name)
    window.close()


def shot_fft_leakage_hanning() -> None:
    _leakage("hanning", "fft_leakage_hanning")


def shot_fft_leakage_flat_top() -> None:
    _leakage("flat_top", "fft_leakage_flat_top")


def shot_fft_a_weighting() -> None:
    """Ten equal tones become the A-curve once weighting is switched on."""
    window = fft_window(
        demo("07_FFT_A_weighting_octave_tones.h5"), df=2.0,
        window_type="flat_top",
        function_type="Auto Spectrum - (EU RMS)",
        display_option="dB - NO reference value",
        weighting="A-weighting",
        log_x="Logarithmic")
    session().processEvents()
    # the floor between the tones runs to -300 dB and would flatten the curve
    window.plot.viewbox.setYRange(-60.0, 10.0, padding=0)
    capture(window, "fft_a_weighting")
    window.close()


def shot_fft_harmonics() -> None:
    """Harmonics at -20, -26 and -40 dB below a 0 dB fundamental."""
    window = fft_window(demo("08_FFT_Harmonics_THD.h5"),
                        function_type="Auto Spectrum - (EU Peak)",
                        display_option="dB - NO reference value")
    session().processEvents()
    window.plot.viewbox.setXRange(0.0, 500.0, padding=0)
    window.plot.viewbox.setYRange(-60.0, 10.0, padding=0)
    capture(window, "fft_harmonics")
    window.close()


def shot_fft_energy_band() -> None:
    """The Energy Band tab summing the harmonics alone, 150-450 Hz."""
    window = fft_window(demo("08_FFT_Harmonics_THD.h5"),
                        function_type="Auto Spectrum - (EU Peak)")
    window.band_start.setValue(150.0)
    window.band_end.setValue(450.0)
    window.tabs.setCurrentWidget(window.band_tab)
    session().processEvents()
    window.plot.viewbox.setXRange(0.0, 500.0, padding=0)
    capture(window, "fft_energy_band")
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
    "time_processing_attributes": shot_time_processing_attributes,
    "time_processing_stats_tab": shot_time_processing_stats,
    "time_processing_scale_tab": shot_time_processing_scale_tab,
    "time_processing_tvm_tab": shot_time_processing_tvm_tab,
    "fft_overview": shot_fft_overview,
    "fft_known_amplitudes": shot_fft_known_amplitudes,
    "fft_leakage_hanning": shot_fft_leakage_hanning,
    "fft_leakage_flat_top": shot_fft_leakage_flat_top,
    "fft_spl_94db": shot_fft_spl_94db,
    "fft_a_weighting": shot_fft_a_weighting,
    "fft_harmonics": shot_fft_harmonics,
    "fft_energy_band": shot_fft_energy_band,
    "tf_overview": shot_tf_overview,
    "tf_phase_crossing": shot_tf_phase_crossing,
    "tf_coherence_interference": shot_tf_coherence_interference,
    "tf_estimator_h1": shot_tf_estimator_h1,
    "tf_estimator_h2": shot_tf_estimator_h2,
    "tfa_overview": shot_tfa_overview,
    "tfa_log_sweep": shot_tfa_log_sweep,
    "tfa_bursts_cursor": shot_tfa_bursts_cursor,
    "tfa_block_size": shot_tfa_block_size,
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
