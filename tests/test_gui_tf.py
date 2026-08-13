"""Transfer Function window - offscreen logic tests."""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from spwb import Signal
from spwb.gui.bridge import WindowManager
from spwb.gui.tf_analysis import TransferFunctionWindow
from spwb.gui.time_processing import TimeProcessingWindow

FS = 1024.0
DT = 1.0 / FS
N = 8192


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def manager(qapp):
    return WindowManager()


@pytest.fixture
def window(manager):
    """A window holding a known system: response = 2.5 x reference."""
    w = TransferFunctionWindow(manager)
    rng = np.random.default_rng(0)
    x = rng.standard_normal(N)
    w.store.add(Signal("force", x, DT, y_unit="N"))
    w.store.add(Signal("accel", 2.5 * x, DT, y_unit="m/s^2"))
    w.freq_resolution.setValue(8.0)
    yield w
    w.close()


def test_window_name_uses_the_tf_prefix(manager):
    w = TransferFunctionWindow(manager)
    assert w.window_name == "TF 00"
    w.close()


def test_first_signal_becomes_reference_rest_responses(window):
    assert [s.name for s in window.signals_with_role("Reference")] == ["force"]
    assert [s.name for s in window.signals_with_role("Response")] == ["accel"]
    assert window.tree.topLevelItem(0).text(1) == "Reference"
    assert window.tree.topLevelItem(1).text(1) == "Response"


def test_a_known_gain_is_recovered_and_plotted(window):
    assert len(window._results) == 1
    tf, coh = window._results[0]
    assert tf.name == "accel / force"
    mid = slice(5, -5)
    np.testing.assert_allclose(tf.y[mid], 2.5, rtol=1e-6)
    np.testing.assert_allclose(coh.y[mid], 1.0, rtol=1e-6)
    assert len(window.plot.plotItem.listDataItems()) == 1


def test_roles_can_be_reassigned(window):
    window.tree.topLevelItem(1).setSelected(True)
    window._set_role("Reference")
    assert len(window.signals_with_role("Reference")) == 2
    assert window.signals_with_role("Response") == []
    assert window._results == []
    assert "at least one reference" in window.statusBar().currentMessage()


def test_double_click_cycles_the_role(window):
    item = window.tree.topLevelItem(0)
    assert item.text(1) == "Reference"
    window._cycle_role(item)
    assert window.tree.topLevelItem(0).text(1) == "Response"
    window._cycle_role(window.tree.topLevelItem(0))
    assert window.tree.topLevelItem(0).text(1) == "(unused)"
    window._cycle_role(window.tree.topLevelItem(0))
    assert window.tree.topLevelItem(0).text(1) == "Reference"


def test_every_combination_is_computed(manager):
    w = TransferFunctionWindow(manager)
    rng = np.random.default_rng(1)
    for name in ("ref1", "ref2", "resp1", "resp2", "resp3"):
        w.store.add(Signal(name, rng.standard_normal(2048), DT))
    for i in range(w.tree.topLevelItemCount()):
        item = w.tree.topLevelItem(i)
        w._roles[item.data(0, Qt.UserRole).sid] = (
            "Reference" if item.text(0).startswith("ref") else "Response")
    w.freq_resolution.setValue(16.0)
    w.recompute()
    assert len(w._results) == 6
    assert w.result_list.topLevelItemCount() == 6
    w.close()


def test_unchecking_a_result_hides_its_trace(manager):
    w = TransferFunctionWindow(manager)
    rng = np.random.default_rng(2)
    x = rng.standard_normal(4096)
    w.store.add(Signal("ref", x, DT))
    w.store.add(Signal("a", 2 * x, DT))
    w.store.add(Signal("b", 3 * x, DT))
    w.freq_resolution.setValue(8.0)
    w.recompute()
    assert len(w.plot.plotItem.listDataItems()) == 2
    w.result_list.topLevelItem(0).setCheckState(0, Qt.Unchecked)
    assert len(w.plot.plotItem.listDataItems()) == 1
    assert len(w._results) == 2            # still computed
    w.close()


@pytest.mark.parametrize("display", ["Magnitude", "Phase (Rad)",
                                     "Phase Unwrap (Degree)", "Coherence"])
def test_every_display_type_plots(window, display):
    window.display_type.setCurrentText(display)
    items = window.plot.plotItem.listDataItems()
    assert len(items) == 1
    assert np.isfinite(items[0].yData).all()


def test_coherence_view_locks_the_y_axis_to_unit_range(window):
    window.display_type.setCurrentText("Coherence")
    lo, hi = window.plot.plotItem.viewRange()[1]
    assert lo <= 0.0 and 1.0 <= hi <= 1.1


def test_estimator_choice_reaches_the_result(window):
    window.estimator.setCurrentText("H2")
    tf, _ = window._results[0]
    assert tf.attributes["TF_Estimator"] == "H2"
    np.testing.assert_allclose(tf.y[5:-5], 2.5, rtol=1e-6)   # noiseless


def test_window_choice_reaches_the_result(window):
    window.window_box.setCurrentText("Hanning")
    tf, _ = window._results[0]
    assert tf.attributes["FFT_Window_Type"] == "hanning"


def test_default_window_is_spwbs_7_term_b_harris(window):
    assert window.window_box.currentText() == "7 Term B-Harris"
    tf, _ = window._results[0]
    assert tf.attributes["FFT_Window_Type"] == "bh_7term"


def test_mismatched_lengths_are_reported_not_crashed(manager):
    w = TransferFunctionWindow(manager)
    rng = np.random.default_rng(3)
    w.store.add(Signal("ref", rng.standard_normal(2048), DT))
    w.store.add(Signal("short", rng.standard_normal(1024), DT))
    w.freq_resolution.setValue(8.0)
    w.recompute()
    assert w._results == []
    assert "same length" in w.statusBar().currentMessage()
    w.close()


def test_log_frequency_axis_drops_the_dc_bin(window):
    window.log_x.setCurrentText("Logarithmic")
    freqs = window.plot.plotItem.listDataItems()[0].xData
    assert freqs[0] > 0 and np.isfinite(freqs).all()


# -- band table and export ---------------------------------------------------
def test_band_table_reports_mean_magnitude_and_coherence(window):
    window.band_start.setValue(50.0)
    window.band_end.setValue(400.0)
    assert window.band_table.rowCount() == 1
    assert float(window.band_table.item(0, 1).text().split()[0]) == \
        pytest.approx(2.5, rel=1e-3)
    assert float(window.band_table.item(0, 2).text()) == pytest.approx(1.0,
                                                                      abs=1e-3)


def test_results_copy_as_tsv(window, qapp):
    window.copy_results()
    lines = qapp.clipboard().text().splitlines()
    assert lines[0] == "Frequency (Hz)\taccel / force [Magnitude]"
    assert len(lines) == window._results[0][0].n_samples + 1


def test_band_table_copies_as_tsv(window, qapp):
    window.copy_band_table()
    text = qapp.clipboard().text()
    assert text.splitlines()[0] == \
        "Transfer Function\tMean |H|\tMean Coherence"


# -- cross-window flow -------------------------------------------------------
def test_time_processing_sends_signals_to_a_tf_window(manager):
    tdp = TimeProcessingWindow(manager)
    rng = np.random.default_rng(4)
    x = rng.standard_normal(4096)
    tdp.store.add(Signal("force", x, DT, y_unit="N"))
    tdp.store.add(Signal("accel", 3.0 * x, DT, y_unit="m/s^2"))

    tf_window = tdp.open_tf_window()
    assert isinstance(tf_window, TransferFunctionWindow)
    assert tf_window.window_name == "TF 00"
    assert [s.name for s in tf_window.store] == ["force", "accel"]
    assert {s.sid for s in tf_window.store}.isdisjoint(
        {s.sid for s in tdp.store})
    tf_window.freq_resolution.setValue(8.0)
    tf, _ = tf_window._results[0]
    assert tf.y_unit == "m/s^2/N"
    np.testing.assert_allclose(tf.y[5:-5], 3.0, rtol=1e-6)
    tf_window.close()
    tdp.close()


def test_removing_a_signal_drops_its_role_and_results(window):
    sig = next(iter(window.store))
    window.store.remove(sig.sid)
    assert sig.sid not in window._roles
    assert window._results == []
