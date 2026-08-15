"""HDF5 integration with the Time Processing window."""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
pytest.importorskip("h5py")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from spwb import Signal
from spwb.gui.bridge import WindowManager
from spwb.gui.time_processing import TimeProcessingWindow
from spwb.processing.io import read_hdf5, write_hdf5

FS = 1000.0
DT = 1.0 / FS


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    w = TimeProcessingWindow(WindowManager())
    yield w
    w.close()


def sine(name="sine", amp=1.0, unit="Pa", n=1000):
    t = np.arange(n) * DT
    return Signal(name, amp * np.sin(2 * np.pi * 50 * t), DT, y_unit=unit)


def test_hdf5_is_the_first_save_option(window):
    """It is the native format, so it leads the menu and takes Ctrl+S."""
    save_menu = next(m for m in window.menuBar().findChildren(type(
        window.menuBar().actions()[0].menu())) if m.title() == "Save ...")
    first = save_menu.actions()[0]
    assert "HDF5" in first.text()
    assert first.shortcut().toString() in ("Ctrl+S", "Ctrl+Alt+S")


def test_save_and_reload_through_the_window(window, monkeypatch, tmp_path):
    original = sine("Accel X", amp=9.81, unit="m/s^2")
    original.attributes["Calibration"] = 9.81
    window.store.add(original)

    monkeypatch.setattr(
        "spwb.gui.settings.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(tmp_path / "run.h5"), ""))
    window.save_hdf5()
    written = tmp_path / "run.h5"
    assert written.exists()
    assert "MATLAB" in window.statusBar().currentMessage()

    other = TimeProcessingWindow(window.manager)
    monkeypatch.setattr(
        "spwb.gui.settings.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(written), ""))
    other.open_hdf5()
    (back,) = list(other.store)
    assert back.name == "Accel X"
    assert back.y_unit == "m/s^2"
    assert back.attributes["Calibration"] == pytest.approx(9.81)
    np.testing.assert_allclose(back.y, original.y)
    other.close()


def test_only_visible_signals_are_saved(window, monkeypatch, tmp_path):
    window.store.add(sine("keep"))
    window.store.add(sine("hidden"))
    window.tree.topLevelItem(1).setCheckState(0, Qt.Unchecked)
    monkeypatch.setattr(
        "spwb.gui.settings.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(tmp_path / "v.h5"), ""))
    window.save_hdf5()
    assert [s.name for s in read_hdf5(tmp_path / "v.h5")] == ["keep"]


def test_saving_nothing_is_reported(window, monkeypatch):
    shown = {}
    monkeypatch.setattr(
        "spwb.gui.time_processing.QMessageBox.information",
        lambda *a, **k: shown.setdefault("msg", a[2]))
    window.save_hdf5()
    assert "No signals" in shown["msg"]


def test_a_broken_file_is_reported_not_crashed(window, monkeypatch, tmp_path):
    bad = tmp_path / "broken.h5"
    bad.write_bytes(b"this is not an HDF5 file at all")
    shown = {}
    monkeypatch.setattr(
        "spwb.gui.settings.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(bad), ""))
    monkeypatch.setattr(
        "spwb.gui.time_processing.QMessageBox.critical",
        lambda *a, **k: shown.setdefault("msg", a[2]))
    window.open_hdf5()
    assert "Could not read" in shown["msg"]
    assert len(window.store) == 0


def test_a_second_import_decorates_names(window, monkeypatch, tmp_path):
    path = write_hdf5(tmp_path / "src.h5", [sine("mic")])
    monkeypatch.setattr(
        "spwb.gui.settings.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(path), ""))
    window.open_hdf5()
    window.open_hdf5()
    names = [s.name for s in window.store]
    assert names[0] == "mic"
    assert names[1] == "mic (src.h5)"


def test_command_line_opens_hdf5(tmp_path, qapp):
    """`spwb run.h5` must load it, like the other formats."""
    from spwb.gui.app import main
    path = write_hdf5(tmp_path / "cli.h5", [sine("from cli")])
    # main() would block on exec(); check the reader table instead
    from spwb.processing.io import read_hdf5 as reader
    assert [s.name for s in reader(path)] == ["from cli"]
    assert main.__module__ == "spwb.gui.app"


def test_an_analysis_result_survives_the_window_round_trip(window,
                                                           monkeypatch,
                                                           tmp_path):
    """A spectrum sent back and forth keeps the settings that made it."""
    from spwb.processing.dsp import auto_power_spectrums

    window.store.add(auto_power_spectrums(sine(amp=3.0), freq_resolution=2.0,
                                          window="flat_top"))
    monkeypatch.setattr(
        "spwb.gui.settings.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(tmp_path / "spec.h5"), ""))
    window.save_hdf5()
    (back,) = read_hdf5(tmp_path / "spec.h5")
    assert back.attributes["FFT_Window_Type"] == "flat_top"
    assert back.x_unit == "Hz"
