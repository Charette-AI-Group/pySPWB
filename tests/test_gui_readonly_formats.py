"""RPC-III, HEAD acoustics and text/CSV in the Time Processing window.

The importers all go through one shared flow (``_import_channels``): list
the channels, let the user pick, import. These tests drive that flow with
the channel dialog auto-accepted, and check the two things a user would
notice - the signals land in the store, and a failure surfaces as a message
rather than a traceback.

Text export is the exception, because it asks a question first: which
number format Excel should expect. That prompt is tested here rather than
in ``test_text.py``, since it is a GUI decision.
"""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QDialog
from test_head_hdf import build_hdf, sine  # the HDF fixture builder
from test_rpc import FRAME, FRAMES, build_rpc  # the RPC fixture builder

from spwb import Signal
from spwb.gui.bridge import WindowManager
from spwb.gui.time_processing import TimeProcessingWindow


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    w = TimeProcessingWindow(WindowManager())
    yield w
    w.close()


@pytest.fixture
def accept_dialogs(monkeypatch):
    """Auto-accept the channel picker with everything selected."""
    from spwb.gui import time_processing as TP

    monkeypatch.setattr(TP.ChannelSelectDialog, "exec",
                        lambda self: QDialog.Accepted)


@pytest.fixture
def rpc_file(tmp_path):
    n = FRAMES * FRAME
    return build_rpc(tmp_path / "run.rsp", [
        ("Accel X", "m/s^2", 0.5, (np.arange(n) % 100).astype("<i2")),
        ("Mic", "Pa", 2.0, np.ones(n, dtype="<i2")),
    ])


def test_open_rpc_imports_every_channel(window, rpc_file, accept_dialogs,
                                        monkeypatch):
    from spwb.gui import time_processing as TP

    monkeypatch.setattr(TP.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(rpc_file), "")))

    window.open_rpc()

    names = [s.name for s in window.store]
    assert names == ["Accel X", "Mic"]
    mic = next(s for s in window.store if s.name == "Mic")
    np.testing.assert_allclose(mic.y, 2.0)
    assert mic.y_unit == "Pa"


def test_open_rpc_reports_a_bad_file_instead_of_raising(window, tmp_path,
                                                        monkeypatch):
    from spwb.gui import time_processing as TP

    junk = tmp_path / "notes.rsp"
    junk.write_bytes(b"not an RPC file" + b"\x00" * 512)
    monkeypatch.setattr(TP.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(junk), "")))
    shown = []
    monkeypatch.setattr(TP.QMessageBox, "critical",
                        staticmethod(lambda _p, title, text: shown.append(text)))

    window.open_rpc()

    assert not len(window.store)
    assert shown and "NUM_HEADER_BLOCKS" in shown[0]


def test_open_head_hdf_imports_a_recording(window, tmp_path, accept_dialogs,
                                           monkeypatch):
    from spwb.gui import time_processing as TP

    path = build_hdf(tmp_path / "Sine 1kHz.hdf",
                     [("Test", "Pa", "pressure", sine())])
    monkeypatch.setattr(TP.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))

    window.open_head_hdf()

    signal, = list(window.store)
    assert signal.name == "Test"
    assert signal.y_unit == "Pa"
    np.testing.assert_allclose(signal.y, sine(), atol=1e-7)


def test_open_head_hdf_reports_a_bad_file_instead_of_raising(window, tmp_path,
                                                             monkeypatch):
    """An HDF5 file with the colliding extension must not misread silently."""
    from spwb.gui import time_processing as TP

    path = tmp_path / "confusing.hdf"
    path.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 512)
    monkeypatch.setattr(TP.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))
    shown = []
    monkeypatch.setattr(TP.QMessageBox, "critical",
                        staticmethod(lambda _p, title, text: shown.append(text)))

    window.open_head_hdf()

    assert not len(window.store)
    assert shown and "start of data" in shown[0]


def test_text_export_asks_which_number_format_excel_expects(window, tmp_path,
                                                            monkeypatch):
    """The right answer depends on the machine that opens the file."""
    from spwb.gui import time_processing as TP

    window.store.add(Signal("Accel", np.arange(16.0), 0.001, y_unit="m/s^2"))
    out = tmp_path / "export.csv"
    monkeypatch.setattr(TP.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    asked = []

    def choose(_parent, _title, _label, items, *a, **k):
        asked.append(items)
        return items[1], True          # the semicolon / decimal comma option

    monkeypatch.setattr(TP.QInputDialog, "getItem", staticmethod(choose))

    window.save_text()

    assert asked, "the user was never asked about the number format"
    text = out.read_text(encoding="utf-8-sig")
    assert ";" in text.splitlines()[2]
    assert "0,0" in text


def test_text_export_then_import_round_trips_through_the_window(
        window, tmp_path, accept_dialogs, monkeypatch):
    from spwb.gui import time_processing as TP

    original = Signal("Accel", np.arange(16.0), 0.001, y_unit="m/s^2")
    window.store.add(original)
    out = tmp_path / "rt.csv"
    monkeypatch.setattr(TP.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(TP.QInputDialog, "getItem", staticmethod(
        lambda *a, **k: ("Comma separated, decimal point  (1,234.5)", True)))
    window.save_text()

    monkeypatch.setattr(TP.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    window.open_text()

    imported = [s for s in window.store if s.sid != original.sid]
    assert len(imported) == 1
    assert imported[0].y_unit == "m/s^2"
    np.testing.assert_array_equal(imported[0].y, original.y)


def test_cancelling_the_number_format_writes_nothing(window, tmp_path,
                                                     monkeypatch):
    from spwb.gui import time_processing as TP

    window.store.add(Signal("Accel", np.arange(8.0), 0.001))
    out = tmp_path / "cancelled.csv"
    monkeypatch.setattr(TP.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(TP.QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: ("", False)))

    window.save_text()

    assert not out.exists()


def test_cancelling_the_picker_imports_nothing(window, rpc_file, monkeypatch):
    from spwb.gui import time_processing as TP

    monkeypatch.setattr(TP.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(rpc_file), "")))
    monkeypatch.setattr(TP.ChannelSelectDialog, "exec",
                        lambda self: QDialog.Rejected)

    window.open_rpc()

    assert not len(window.store)
