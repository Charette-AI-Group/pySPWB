"""GUI logic tests - run offscreen, no display required.

These drive the window API directly rather than synthesising clicks: the
point is to prove the architecture (per-window stores, cross-window
sharing, plot/list wiring), not to test Qt itself.
"""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from spwb import Signal
from spwb.gui.bridge import StoreBridge, WindowManager
from spwb.gui.time_processing import TimeProcessingWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def manager(qapp):
    return WindowManager()


@pytest.fixture
def window(manager):
    w = TimeProcessingWindow(manager)
    yield w
    w.close()


def make_signal(name="sine", f=50.0, fs=1024.0, n=1024, unit="Pa"):
    dt = 1.0 / fs
    t = np.arange(n) * dt
    return Signal(name, np.sin(2 * np.pi * f * t), dt, y_unit=unit)


# -- bridge ------------------------------------------------------------------
def test_bridge_emits_qt_signals(qapp):
    bridge = StoreBridge()
    seen = []
    bridge.signal_added.connect(lambda s: seen.append(("added", s.name)))
    bridge.signal_removed.connect(lambda s: seen.append(("removed", s.name)))
    sig = bridge.store.add(make_signal("a"))
    bridge.store.remove(sig.sid)
    assert seen == [("added", "a"), ("removed", "a")]
    bridge.close()


def test_window_names_follow_labview_convention(manager):
    names = []
    windows = []
    for _ in range(3):
        w = TimeProcessingWindow(manager)
        windows.append(w)
        names.append(w.window_name)
    assert names == ["TDP 00", "TDP 01", "TDP 02"]
    assert len(manager) == 3
    windows[1].close()
    assert len(manager) == 2
    assert windows[0] in manager.windows and windows[1] not in manager.windows
    for w in windows:
        w.close()


# -- list / plot wiring ------------------------------------------------------
def test_adding_signal_populates_list_and_plot(window):
    assert window.tree.topLevelItemCount() == 0
    window.store.add(make_signal("sine", fs=2048.0, n=2048))
    assert window.tree.topLevelItemCount() == 1
    item = window.tree.topLevelItem(0)
    assert item.text(0) == "sine"
    assert item.text(1) == "2048"
    assert item.text(2) == "2048"
    assert item.text(4) == "Pa"
    assert len(window.plot.plotItem.listDataItems()) == 1


def test_unchecking_hides_trace_without_deleting(window):
    window.store.add(make_signal("a"))
    window.store.add(make_signal("b"))
    assert len(window.plot.plotItem.listDataItems()) == 2
    window.tree.topLevelItem(0).setCheckState(0, Qt.Unchecked)
    assert len(window.plot.plotItem.listDataItems()) == 1
    assert len(window.store) == 2          # still there, just invisible


def test_delete_invisible_signals(window):
    window.store.add(make_signal("keep"))
    window.store.add(make_signal("drop"))
    window.tree.topLevelItem(1).setCheckState(0, Qt.Unchecked)
    window.delete_invisible()
    assert [s.name for s in window.store] == ["keep"]


def test_details_panel_shows_attributes(window):
    sig = make_signal("accel")
    sig.attributes["Data Source"] = r"C:\data\run.tdms"
    window.store.add(sig)
    window.tree.topLevelItem(0).setSelected(True)
    text = window.details.toPlainText()
    assert "accel" in text
    assert "Data Source" in text and "run.tdms" in text
    assert "fs      : 1024 Hz" in text


# -- the defining feature: multi-instance signal sharing ---------------------
def test_import_from_another_window_copies_signals(manager):
    source = TimeProcessingWindow(manager)
    target = TimeProcessingWindow(manager)
    source.store.add(make_signal("shared"))

    from spwb.gui.dialogs import ImportFromWindowDialog
    dialog = ImportFromWindowDialog(manager.others(target), target)
    assert dialog.window_box.count() == 1
    assert dialog.list.count() == 1
    imported = dialog.selected_signals()          # copy mode is the default
    for sig in imported:
        target.store.add(sig)

    assert len(target.store) == 1
    copied = next(iter(target.store))
    original = next(iter(source.store))
    assert copied.name == original.name
    assert copied.sid != original.sid             # independent identity
    np.testing.assert_array_equal(copied.y, original.y)

    # mutating the source must not affect the imported copy
    source.store.update(original.with_(name="renamed"))
    assert next(iter(target.store)).name == "shared"

    source.close()
    target.close()


def test_import_by_reference_shares_identity(manager):
    source = TimeProcessingWindow(manager)
    target = TimeProcessingWindow(manager)
    source.store.add(make_signal("live"))

    from spwb.gui.dialogs import ImportFromWindowDialog
    dialog = ImportFromWindowDialog(manager.others(target), target)
    dialog.copy_box.setChecked(False)
    for sig in dialog.selected_signals():
        target.store.add(sig)

    assert next(iter(target.store)).sid == next(iter(source.store)).sid
    source.close()
    target.close()


def test_duplicate_window_clones_content(window):
    window.store.add(make_signal("a"))
    window.store.add(make_signal("b"))
    clone = window.duplicate_window()
    assert clone.window_name != window.window_name
    assert [s.name for s in clone.store] == ["a", "b"]
    assert {s.sid for s in clone.store}.isdisjoint({s.sid for s in window.store})
    clone.close()


def test_new_window_starts_empty(window):
    window.store.add(make_signal("a"))
    fresh = window.new_window()
    assert len(fresh.store) == 0
    assert len(window.store) == 1
    fresh.close()


# -- generators --------------------------------------------------------------
@pytest.mark.parametrize("kind", ["Sine", "Square", "Triangle", "Sine Sweep",
                                  "Random (Gaussian)", "Random (Uniform)"])
def test_create_signal_dialog_builds_every_kind(qapp, kind):
    from spwb.gui.dialogs import CreateSignalDialog
    dialog = CreateSignalDialog()
    dialog.kind.setCurrentText(kind)
    dialog.fs.setValue(8192.0)
    dialog.duration.setValue(0.25)
    sig = dialog.build()
    assert sig.n_samples == 2048
    assert sig.fs == pytest.approx(8192.0)
    assert np.isfinite(sig.y).all()
    assert sig.attributes["Data Source"].startswith("Generated")


def test_generated_sine_lands_on_the_right_bin(qapp):
    from spwb.gui.dialogs import CreateSignalDialog
    from spwb.processing.dsp import spectral as S
    dialog = CreateSignalDialog()
    dialog.kind.setCurrentText("Sine")
    dialog.fs.setValue(4096.0)
    dialog.duration.setValue(1.0)
    dialog.freq.setValue(256.0)
    dialog.amplitude.setValue(3.0)
    spec = S.auto_power_spectrums(dialog.build(), freq_resolution=1.0)
    k = int(round(256.0 / spec.dt))
    assert spec.y[k] == pytest.approx(3.0 ** 2 / 2, rel=1e-6)


# -- file round trip through the window ---------------------------------------
def test_window_save_and_reload_via_tdms(window, manager, tmp_path):
    pytest.importorskip("nptdms")
    from spwb.processing.io import read_tdms, write_tdms
    window.store.add(make_signal("accel", unit="m/s^2"))
    path = tmp_path / "out.tdms"
    write_tdms(path, list(window.store))

    other = TimeProcessingWindow(manager)
    for sig in read_tdms(path):
        other.store.add(sig)
    assert [s.name for s in other.store] == ["accel"]
    assert next(iter(other.store)).y_unit == "m/s^2"
    other.close()


def test_the_signal_list_and_attributes_box_are_user_adjustable(qapp):
    """Both splits in the Time Processing window must be draggable.

    The attributes box used to be capped at a fixed 150 px, so the only
    adjustable split was left/right. Which of the two panes needs the room
    changes with the session - many signals, or one signal with a lot of
    attributes - so it belongs to the user.
    """
    from PySide6.QtWidgets import QSplitter

    window = TimeProcessingWindow(WindowManager())
    try:
        outer = window.centralWidget()
        left = outer.widget(0)

        assert isinstance(outer, QSplitter)
        assert isinstance(left, QSplitter), "the left panel is not a splitter"
        assert left.orientation() == Qt.Vertical
        assert left.count() == 2

        # no fixed cap, or the splitter could not grow it
        assert window.details.maximumHeight() > 1000

        left.setSizes([120, 480])
        assert left.sizes()[1] > left.sizes()[0]

        left.setSizes([600, 0])          # dragging it shut hides attributes
        assert left.sizes()[1] == 0
    finally:
        window.close()


def test_signal_table_columns_can_be_resized_by_the_user(qapp):
    """Stretch and ResizeToContents look fine but cannot be dragged.

    Qt only lets a divider be dragged in Interactive or Fixed mode; the
    other two compute the width themselves, which left long signal names
    elided with no way to widen the column.
    """
    from PySide6.QtWidgets import QHeaderView

    window = TimeProcessingWindow(WindowManager())
    try:
        header = window.tree.header()
        for col in range(window.tree.columnCount()):
            assert header.sectionResizeMode(col) == QHeaderView.Interactive, (
                f"column {col} cannot be dragged")
        assert not header.stretchLastSection()
        assert window.tree.columnWidth(0) > window.tree.columnWidth(1)
    finally:
        window.close()


def test_column_widths_survive_a_list_rebuild(qapp):
    """_refresh_list clears the tree on every change; widths must persist."""
    window = TimeProcessingWindow(WindowManager())
    try:
        window.store.add(Signal("first", np.zeros(64), 0.01, y_unit="V"))
        window.tree.setColumnWidth(0, 337)

        window.store.add(Signal("second", np.zeros(64), 0.01, y_unit="V"))

        assert window.tree.topLevelItemCount() == 2
        assert window.tree.columnWidth(0) == 337
    finally:
        window.close()
