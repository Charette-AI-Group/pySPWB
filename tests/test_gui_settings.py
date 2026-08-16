"""Remembered browse folders, one per file type and operation.

These tests redirect ``settings._store`` at a throwaway INI file. Without
that they would write to the real user settings - the registry on Windows -
and the suite would quietly change where the application browses next.
"""
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from spwb.gui import settings


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store(qapp, tmp_path, monkeypatch):
    """An isolated settings store, so the real one is never touched."""
    ini = tmp_path / "settings.ini"
    obj = QSettings(str(ini), QSettings.IniFormat)
    monkeypatch.setattr(settings, "_store", lambda: obj)
    return obj


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home folder, so the fallback is checkable."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake))
    return fake


# -- the fallback rule -----------------------------------------------------
def test_with_nothing_remembered_browsing_starts_at_home(store, home):
    assert settings.last_dir("tdms", "open") == str(home)


def test_a_folder_that_no_longer_exists_falls_back_to_home(store, home,
                                                           tmp_path):
    """Drives get unmounted and folders get renamed; the dialog must cope."""
    gone = tmp_path / "removable" / "data"
    gone.mkdir(parents=True)
    settings.remember_dir("tdms", "open", gone / "run.tdms")
    assert settings.last_dir("tdms", "open") == str(gone)

    for item in (gone, gone.parent):
        item.rmdir()

    assert settings.last_dir("tdms", "open") == str(home)


def test_a_remembered_folder_that_still_exists_is_used(store, home, tmp_path):
    folder = tmp_path / "measurements"
    folder.mkdir()

    settings.remember_dir("wave", "open", folder / "take1.wav")

    assert settings.last_dir("wave", "open") == str(folder)


# -- one setting per file type and operation -------------------------------
def test_open_and_save_are_remembered_separately(store, home, tmp_path):
    """Read from the measurement folder, write to the report folder."""
    measurements = tmp_path / "measurements"
    reports = tmp_path / "reports"
    measurements.mkdir()
    reports.mkdir()

    settings.remember_dir("tdms", "open", measurements / "run.tdms")
    settings.remember_dir("tdms", "save", reports / "out.tdms")

    assert settings.last_dir("tdms", "open") == str(measurements)
    assert settings.last_dir("tdms", "save") == str(reports)


def test_each_file_type_is_remembered_separately(store, home, tmp_path):
    folders = {}
    for kind in settings.KINDS:
        folder = tmp_path / kind
        folder.mkdir()
        folders[kind] = folder
        settings.remember_dir(kind, "open", folder / f"file.{kind}")

    for kind, folder in folders.items():
        assert settings.last_dir(kind, "open") == str(folder)


def test_a_folder_may_be_given_instead_of_a_file(store, home, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()

    settings.remember_dir("hdf5", "save", folder)

    assert settings.last_dir("hdf5", "save") == str(folder)


def test_forget_clears_every_remembered_folder(store, home, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    settings.remember_dir("hdf5", "open", folder)
    settings.remember_dir("wave", "save", folder)

    settings.forget_dirs()

    assert settings.last_dir("hdf5", "open") == str(home)
    assert settings.last_dir("wave", "save") == str(home)


@pytest.mark.parametrize("kind,mode", [
    ("not_a_format", "open"),
    ("tdms", "delete"),
])
def test_unknown_keys_are_refused(store, kind, mode):
    """A typo must fail loudly, not silently forget the folder."""
    with pytest.raises(ValueError):
        settings.last_dir(kind, mode)


# -- the dialog wrappers ---------------------------------------------------
def test_open_file_starts_where_it_left_off_and_records_the_result(
        store, home, tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "a.tdms").write_bytes(b"")
    (second / "b.tdms").write_bytes(b"")
    seen = []

    def fake(parent, caption, directory, filters):
        seen.append(directory)
        return str(second / "b.tdms"), ""

    monkeypatch.setattr(settings.QFileDialog, "getOpenFileName",
                        staticmethod(fake))

    settings.remember_dir("tdms", "open", first / "a.tdms")
    settings.open_file(None, "Open", "tdms", "*.tdms")
    assert seen[-1] == str(first)          # started where we left off

    settings.open_file(None, "Open", "tdms", "*.tdms")
    assert seen[-1] == str(second)         # and moved on to the new folder


def test_cancelling_a_dialog_does_not_forget_the_folder(store, home, tmp_path,
                                                        monkeypatch):
    folder = tmp_path / "data"
    folder.mkdir()
    settings.remember_dir("wave", "open", folder)
    monkeypatch.setattr(settings.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("", "")))

    assert settings.open_file(None, "Open", "wave", "*.wav") == ""
    assert settings.last_dir("wave", "open") == str(folder)


def test_save_file_uses_the_save_folder_not_the_open_one(store, home, tmp_path,
                                                         monkeypatch):
    reading = tmp_path / "reading"
    writing = tmp_path / "writing"
    reading.mkdir()
    writing.mkdir()
    settings.remember_dir("hdf5", "open", reading)
    settings.remember_dir("hdf5", "save", writing)
    seen = []
    monkeypatch.setattr(settings.QFileDialog, "getSaveFileName", staticmethod(
        lambda parent, caption, directory, filters: (seen.append(directory)
                                                     or ("", ""))))

    settings.save_file(None, "Save", "hdf5", "*.h5")

    assert seen == [str(writing)]


def test_open_files_remembers_the_folder_of_the_first_file(store, home,
                                                           tmp_path,
                                                           monkeypatch):
    folder = tmp_path / "waves"
    folder.mkdir()
    chosen = [str(folder / "a.wav"), str(folder / "b.wav")]
    monkeypatch.setattr(settings.QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: (chosen, "")))

    assert settings.open_files(None, "Open", "wave", "*.wav") == chosen
    assert settings.last_dir("wave", "open") == str(folder)


# -- through the window ----------------------------------------------------
def test_the_window_remembers_where_a_signal_was_opened_from(
        store, home, tmp_path, monkeypatch):
    pytest.importorskip("pyqtgraph")
    pytest.importorskip("h5py")
    from spwb import Signal
    from spwb.gui.bridge import WindowManager
    from spwb.gui.time_processing import TimeProcessingWindow
    from spwb.processing.io import write_hdf5

    folder = tmp_path / "session"
    folder.mkdir()
    written = write_hdf5(folder / "run.h5",
                         [Signal("Accel", [1.0, 2.0, 3.0], 0.01)])

    window = TimeProcessingWindow(WindowManager())
    try:
        monkeypatch.setattr(settings.QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (str(written), "")))
        window.open_hdf5()

        assert len(window.store) == 1
        assert settings.last_dir("hdf5", "open") == str(folder)
        # ...and the *save* folder is untouched by an open
        assert settings.last_dir("hdf5", "save") == str(home)
    finally:
        window.close()


# -- remembered table layouts ----------------------------------------------
def _window():
    from spwb.gui.bridge import WindowManager
    from spwb.gui.time_processing import TimeProcessingWindow
    return TimeProcessingWindow(WindowManager())


def test_column_widths_and_order_survive_a_restart(store, qapp):
    pytest.importorskip("pyqtgraph")

    first = _window()
    try:
        first.tree.setColumnWidth(0, 333)
        first.tree.setColumnWidth(4, 111)
        first.tree.header().moveSection(4, 0)      # drag Unit to the front
    finally:
        first.close()                              # saving happens on close

    second = _window()
    try:
        assert second.tree.columnWidth(0) == 333
        assert second.tree.columnWidth(4) == 111
        assert second.tree.header().logicalIndex(0) == 4
    finally:
        second.close()


def test_a_layout_from_a_different_column_set_is_discarded(store, qapp,
                                                           monkeypatch):
    """Bumping HEADER_VERSION must fall back to defaults, not misapply."""
    pytest.importorskip("pyqtgraph")

    first = _window()
    try:
        first.tree.setColumnWidth(0, 333)
    finally:
        first.close()

    monkeypatch.setattr(settings, "HEADER_VERSION",
                        settings.HEADER_VERSION + 1)
    second = _window()
    try:
        assert second.tree.columnWidth(0) != 333
    finally:
        second.close()


def test_forget_layout_brings_the_defaults_back(store, qapp):
    pytest.importorskip("pyqtgraph")

    first = _window()
    try:
        first.tree.setColumnWidth(0, 333)
    finally:
        first.close()

    settings.forget_layout()

    second = _window()
    try:
        assert second.tree.columnWidth(0) != 333
    finally:
        second.close()


def test_restore_header_reports_whether_it_did_anything(store, qapp):
    from PySide6.QtWidgets import QTreeWidget

    tree = QTreeWidget()
    tree.setHeaderLabels(["a", "b"])

    assert settings.restore_header("never_saved", tree.header()) is False

    settings.save_header("saved", tree.header())
    assert settings.restore_header("saved", tree.header()) is True
