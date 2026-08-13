"""The Time Processing window's analysis tabs - offscreen logic tests."""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from spwb import Signal
from spwb.gui.bridge import WindowManager
from spwb.gui.time_processing import TimeProcessingWindow

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


def sine(name="sine", amp=1.0, f=50.0, n=4000, unit="V"):
    t = np.arange(n) * DT
    return Signal(name, amp * np.sin(2 * np.pi * f * t), DT, y_unit=unit)


def test_the_three_tabs_are_present(window):
    labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert labels == ["Scale Signals", "Stats", "TV Metrics"]


# -- Scale Signals -----------------------------------------------------------
def test_scale_tab_lists_signals_with_neutral_defaults(window):
    window.store.add(sine("accel", unit="V"))
    tab = window.scale_tab
    tab.refresh()
    assert tab.table.rowCount() == 1
    assert tab.table.item(0, 0).text() == "accel"
    assert tab.table.item(0, 1).text() == "V"
    assert tab.table.item(0, 2).text() == "1"       # neutral factor
    assert tab.table.item(0, 3).text() == "0"       # neutral offset


def test_applying_a_calibration_rewrites_the_signal(window):
    window.store.add(sine("ch0", amp=1.0, unit="V"))
    tab = window.scale_tab
    tab.refresh()
    tab.table.setItem(0, 0, QTableWidgetItem("Accel X"))
    tab.table.setItem(0, 1, QTableWidgetItem("m/s^2"))
    tab.table.setItem(0, 2, QTableWidgetItem("9.81"))
    tab.table.setItem(0, 3, QTableWidgetItem("1.5"))
    tab.apply()

    sig = next(iter(window.store))
    assert sig.name == "Accel X" and sig.y_unit == "m/s^2"
    assert sig.y.max() == pytest.approx(9.81 + 1.5, rel=1e-3)
    assert sig.attributes["Scale_Factor"] == 9.81
    # the signal keeps its identity, so the plot and list follow it
    assert len(window.store) == 1


def test_apply_is_a_no_op_when_nothing_changed(window):
    window.store.add(sine("a"))
    before = next(iter(window.store)).y.copy()
    window.scale_tab.refresh()
    window.scale_tab.apply()
    np.testing.assert_array_equal(next(iter(window.store)).y, before)
    assert "Nothing to apply" in window.statusBar().currentMessage()


def test_a_bad_number_is_reported_and_leaves_data_alone(window, monkeypatch):
    window.store.add(sine("a", amp=2.0))
    tab = window.scale_tab
    tab.refresh()
    tab.table.setItem(0, 2, QTableWidgetItem("9,81"))   # comma, not a number
    shown = {}
    monkeypatch.setattr("spwb.gui.analysis_tabs.QMessageBox.warning",
                        lambda *a, **k: shown.setdefault("msg", a[2]))
    tab.apply()
    assert "not a number" in shown["msg"]
    assert np.abs(next(iter(window.store)).y).max() == pytest.approx(2.0,
                                                                     rel=1e-3)


def test_reset_discards_staged_edits(window):
    window.store.add(sine("a"))
    tab = window.scale_tab
    tab.refresh()
    tab.table.setItem(0, 2, QTableWidgetItem("50"))
    tab.refresh()                       # Reset button calls this
    assert tab.table.item(0, 2).text() == "1"


def test_normalize_to_itself_from_the_tab(window):
    window.store.add(sine("loud", amp=4.0))
    window.store.add(sine("quiet", amp=1.0))
    tab = window.scale_tab
    tab.normalize_box.setCurrentText("To itself")
    tab.normalize()
    peaks = [np.abs(s.y).max() for s in window.store]
    assert all(p == pytest.approx(1.0, rel=1e-3) for p in peaks)


def test_normalize_to_all_keeps_relative_levels(window):
    window.store.add(sine("loud", amp=4.0))
    window.store.add(sine("quiet", amp=1.0))
    tab = window.scale_tab
    tab.normalize_box.setCurrentText("To the max levels of ALL the signals")
    tab.normalize()
    peaks = [np.abs(s.y).max() for s in window.store]
    assert peaks[0] == pytest.approx(1.0, rel=1e-3)
    assert peaks[1] == pytest.approx(0.25, rel=1e-3)


def test_normalize_with_no_signals_is_reported(window):
    window.scale_tab.normalize()
    assert "No signals" in window.statusBar().currentMessage()


# -- Stats -------------------------------------------------------------------
def test_stats_tab_reports_known_values(window):
    window.store.add(Signal("dc", np.full(500, 2.5), DT, y_unit="V"))
    tab = window.stats_tab
    tab.refresh()
    assert tab.table.rowCount() == 1
    row = [tab.table.item(0, c).text() for c in range(tab.table.columnCount())]
    assert row[0] == "dc"
    assert row[1].startswith("2.5") and row[2].startswith("2.5")
    assert row[4].startswith("2.5")             # RMS
    assert row[5].startswith("0")               # peak-peak
    assert row[7] == "500"                      # samples
    assert row[8].startswith("500")             # duration ms


def test_stats_update_when_a_signal_is_added(window):
    window.tabs.setCurrentWidget(window.stats_tab)
    window.store.add(sine("a"))
    assert window.stats_tab.table.rowCount() == 1
    window.store.add(sine("b"))
    assert window.stats_tab.table.rowCount() == 2


def test_stats_copy_as_tsv(window, qapp):
    window.store.add(sine("a"))
    window.stats_tab.refresh()
    window.stats_tab.copy()
    text = qapp.clipboard().text()
    assert text.splitlines()[0].startswith("Signal\tMin\tMax")
    assert "\ta\t" in text or text.splitlines()[1].startswith("a\t")


# -- TV Metrics --------------------------------------------------------------
@pytest.fixture
def burst_window(window):
    y = 0.1 * np.ones(10_000)
    y[4000:6000] = 2.0
    window.store.add(Signal("burst", y, DT, y_unit="Pa"))
    return window


def test_trend_is_added_as_a_new_signal(burst_window):
    tab = burst_window.tvm_tab
    tab.trend.setCurrentText("RMS")
    tab.step.setValue(100.0)
    tab.length.setValue(200.0)
    tab.compute()

    assert len(burst_window.store) == 2
    trend = [s for s in burst_window.store if "TVM_Trend_Type" in s.attributes]
    assert len(trend) == 1
    out = trend[0]
    assert out.name == "burst (TVM)"
    assert out.attributes["TVM_Trend_Type"] == "RMS"
    assert out.y.max() == pytest.approx(2.0, abs=1e-6)
    assert out.y.min() == pytest.approx(0.1, abs=1e-6)
    # it plots alongside the source
    assert len(burst_window.plot.plotItem.listDataItems()) == 2


def test_summary_table_describes_the_trend(burst_window):
    tab = burst_window.tvm_tab
    tab.step.setValue(100.0)
    tab.length.setValue(200.0)
    tab.compute()
    assert tab.summary.rowCount() == 1
    assert tab.summary.item(0, 0).text() == "burst (TVM)"
    assert int(tab.summary.item(0, 1).text()) > 10


def test_trends_are_not_trended_again(burst_window):
    tab = burst_window.tvm_tab
    tab.step.setValue(200.0)
    tab.length.setValue(1000.0)
    tab.compute()
    tab.compute()
    trends = [s for s in burst_window.store
              if "TVM_Trend_Type" in s.attributes]
    assert len(trends) == 2                  # one per run, not one per signal
    assert all(t.name == "burst (TVM)" for t in trends)


@pytest.mark.parametrize("trend", ["RMS", "Absolute Peak", "Range",
                                   "Standard Deviation", "Variance",
                                   "Skewness", "Kurtosis"])
def test_every_trend_type_computes_from_the_tab(window, trend):
    """Real data (noisy) - every trend must be finite everywhere."""
    rng = np.random.default_rng(3)
    y = 0.1 * rng.standard_normal(10_000)
    y[4000:6000] += 2.0
    window.store.add(Signal("noisy", y, DT, y_unit="Pa"))
    tab = window.tvm_tab
    tab.trend.setCurrentText(trend)
    tab.step.setValue(200.0)
    tab.length.setValue(1000.0)
    tab.compute()
    out = next(s for s in window.store
               if s.attributes.get("TVM_Trend_Type") == trend)
    assert np.isfinite(out.y).all()


@pytest.mark.parametrize("trend", ["Skewness", "Kurtosis"])
def test_shape_trends_are_nan_over_a_perfectly_constant_block(burst_window,
                                                              trend):
    """Skewness and kurtosis of a constant block are 0/0, so NaN is the
    honest answer; the plot shows a gap rather than a made-up number."""
    tab = burst_window.tvm_tab
    tab.trend.setCurrentText(trend)
    tab.step.setValue(200.0)
    tab.length.setValue(1000.0)
    tab.compute()
    out = next(s for s in burst_window.store
               if s.attributes.get("TVM_Trend_Type") == trend)
    assert np.isnan(out.y).any()          # the flat regions
    assert np.isfinite(out.y).any()       # but not everywhere


def test_too_long_a_window_is_reported_not_crashed(burst_window):
    tab = burst_window.tvm_tab
    tab.step.setValue(100.0)
    tab.length.setValue(1e6)                 # far longer than the record
    tab.compute()
    assert "signal has" in burst_window.statusBar().currentMessage()
    assert len(burst_window.store) == 1      # nothing added


def test_compute_with_no_signals_is_reported(window):
    window.tvm_tab.compute()
    assert "No signals" in window.statusBar().currentMessage()


def test_only_visible_signals_are_trended(burst_window):
    burst_window.store.add(sine("other"))
    # hide the second signal
    burst_window.tree.topLevelItem(1).setCheckState(0, Qt.Unchecked)
    tab = burst_window.tvm_tab
    tab.step.setValue(200.0)
    tab.length.setValue(1000.0)
    tab.compute()
    trends = [s for s in burst_window.store
              if "TVM_Trend_Type" in s.attributes]
    assert [t.name for t in trends] == ["burst (TVM)"]
