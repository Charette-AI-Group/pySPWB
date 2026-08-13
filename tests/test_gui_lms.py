"""Adaptive Filtering window - offscreen logic tests."""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication

from spwb import Signal
from spwb.gui.bridge import WindowManager
from spwb.gui.lms_analysis import LMSWindow
from spwb.gui.time_processing import TimeProcessingWindow

FS = 2000.0
DT = 1.0 / FS
N = 8000


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def manager(qapp):
    return WindowManager()


def loaded(manager, seed=0):
    """A window holding a reference and a signal contaminated by it."""
    w = LMSWindow(manager)
    rng = np.random.default_rng(seed)
    t = np.arange(N) * DT
    noise = rng.standard_normal(N)
    wanted = np.sin(2 * np.pi * 60 * t)
    contamination = 0.8 * np.roll(noise, 5)
    w.store.add(Signal("ref", noise, DT, y_unit="V"))
    w.store.add(Signal("mic", wanted + contamination, DT, y_unit="Pa"))
    return w


def test_window_name_uses_the_lms_prefix(manager):
    w = LMSWindow(manager)
    assert w.window_name == "LMS 00"
    w.close()


def test_selectors_fill_and_default_to_different_signals(manager):
    w = loaded(manager)
    assert w.reference_box.count() == 2
    assert w.noisy_box.count() == 2
    assert w.reference_box.currentData().name == "ref"
    assert w.noisy_box.currentData().name == "mic"
    w.close()


def test_running_cleans_the_signal(manager):
    w = loaded(manager)
    w.filter_length.setValue(32)
    w.step_size.setValue(0.1)
    w.run()
    assert w._result is not None
    assert w._result.noise_reduction_db > 1.0
    assert w.add_button.isEnabled()
    assert len(w.signal_plot.plotItem.listDataItems()) == 2
    assert len(w.convergence_plot.plotItem.listDataItems()) == 1
    assert len(w.coefficient_plot.plotItem.listDataItems()) == 1
    w.close()


def test_summary_reports_level_and_convergence(manager):
    w = loaded(manager)
    w.filter_length.setValue(32)
    w.run()
    text = w.summary.text()
    assert "dB" in text and "Convergence" in text
    assert "Normalized LMS" in text
    w.close()


def test_adding_the_result_puts_it_in_the_store(manager):
    w = loaded(manager)
    w.filter_length.setValue(32)
    w.run()
    w.add_result()
    names = [s.name for s in w.store]
    assert "mic (LMS)" in names
    assert len(w.store) == 3                     # only the filtered one
    w.close()


def test_keeping_the_removed_part_adds_both(manager):
    w = loaded(manager)
    w.filter_length.setValue(32)
    w.keep_removed.setChecked(True)
    w.run()
    w.add_result()
    names = [s.name for s in w.store]
    assert "mic (LMS)" in names and "mic (removed)" in names
    w.close()


def test_results_are_not_offered_as_inputs(manager):
    """A filtered output must not become a reference on the next run."""
    w = loaded(manager)
    w.filter_length.setValue(32)
    w.run()
    w.add_result()
    assert w.reference_box.count() == 2          # still only the originals
    assert all("LMS" not in w.reference_box.itemText(i)
               for i in range(w.reference_box.count()))
    w.close()


def test_the_same_signal_for_both_roles_is_refused(manager, monkeypatch):
    w = loaded(manager)
    w.noisy_box.setCurrentIndex(0)               # both are "ref" now
    shown = {}
    monkeypatch.setattr("spwb.gui.lms_analysis.QMessageBox.information",
                        lambda *a, **k: shown.setdefault("msg", a[2]))
    w.run()
    assert "same" in shown["msg"]
    assert w._result is None
    w.close()


def test_a_diverging_setting_is_explained_not_crashed(manager):
    w = loaded(manager)
    w.filter_class.setCurrentText("LMS")
    w.step_size.setValue(1.5)                    # far above the LMS bound
    w.filter_length.setValue(32)
    w.run()
    assert w._result is None
    assert not w.add_button.isEnabled()
    assert "diverged" in w.summary.text()
    assert "Normalized LMS" in w.summary.text()  # tells them what to do
    w.close()


def test_changing_a_role_invalidates_the_stale_result(manager):
    w = loaded(manager)
    w.filter_length.setValue(32)
    w.run()
    assert w.add_button.isEnabled()
    w.reference_box.setCurrentIndex(1)
    assert w._result is None
    assert not w.add_button.isEnabled()
    w.close()


def test_time_processing_sends_signals_to_an_lms_window(manager):
    tdp = TimeProcessingWindow(manager)
    rng = np.random.default_rng(3)
    noise = rng.standard_normal(N)
    tdp.store.add(Signal("ref", noise, DT))
    tdp.store.add(Signal("mic", np.roll(noise, 4) * 0.7, DT))

    lms = tdp.open_lms_window()
    assert isinstance(lms, LMSWindow)
    assert lms.window_name == "LMS 00"
    assert [s.name for s in lms.store] == ["ref", "mic"]
    assert {s.sid for s in lms.store}.isdisjoint({s.sid for s in tdp.store})
    lms.close()
    tdp.close()


def test_an_empty_window_reports_rather_than_running(manager):
    w = LMSWindow(manager)
    w.run()
    assert w._result is None
    assert "reference" in w.statusBar().currentMessage()
    w.close()
