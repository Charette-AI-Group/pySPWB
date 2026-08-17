"""The demonstration datasets, and the File menu entry that creates them.

The manuals teach through these files, so two things matter: that the
generator lives in the package (a wheel install must be able to make them,
not just a git checkout), and that the menu entry writes them where the
user asked without silently destroying anything.
"""
import os

import numpy as np
import pytest

pytest.importorskip("h5py", reason="the datasets are written as HDF5")

from spwb.demo import DATASET_COUNT, write_demo_data
from spwb.processing.io import read_hdf5


def test_generator_ships_in_the_package():
    """Importable from the installed package, not from tools/.

    The whole point of moving it: `pip install spwb` users get the demo
    data too. A test that only ran from a checkout would not notice a
    packaging mistake, so this asserts the module's home explicitly.
    """
    import spwb.demo

    assert spwb.demo.__name__ == "spwb.demo"
    assert "tools" not in spwb.demo.__file__.replace("\\", "/").split("/")


def test_writes_the_whole_set(tmp_path):
    written = write_demo_data(tmp_path)

    assert len(written) == DATASET_COUNT == 14
    assert all(p.is_file() and p.stat().st_size > 0 for p in written)
    assert (tmp_path / "README.txt").is_file()
    # numbered so the manuals can refer to "demo file 06"
    assert [p.name[:2] for p in written] == [f"{i:02d}" for i in range(1, 15)]


def test_creates_a_folder_that_does_not_exist_yet(tmp_path):
    target = tmp_path / "nested" / "demo data"
    written = write_demo_data(target)

    assert target.is_dir()
    assert len(written) == DATASET_COUNT


def test_progress_is_reported_once_per_file(tmp_path):
    seen = []
    write_demo_data(tmp_path, progress=lambda *args: seen.append(args))

    assert len(seen) == DATASET_COUNT
    assert [done for done, _total, _path in seen] == list(range(1, 15))
    assert {total for _done, total, _path in seen} == {DATASET_COUNT}
    assert all(path.is_file() for _done, _total, path in seen)


def test_signals_are_reproducible(tmp_path):
    """Seeded synthesis: the same data every time, so the manuals' numbers
    stay true. The HDF5 container is not byte-stable, only the signals."""
    first = write_demo_data(tmp_path / "a")
    second = write_demo_data(tmp_path / "b")

    for a, b in zip(first, second, strict=True):
        left = {s.name: s.y for s in read_hdf5(a)}
        right = {s.name: s.y for s in read_hdf5(b)}
        assert left.keys() == right.keys()
        for name in left:
            assert np.array_equal(left[name], right[name]), f"{a.name}:{name}"


def test_signals_carry_their_expected_values(tmp_path):
    """Each signal documents what it should measure - that is the point."""
    write_demo_data(tmp_path)
    signals = read_hdf5(tmp_path / "01_TimeProcessing_Stats_known_values.h5")

    assert all("Demo Note" in s.attributes for s in signals)
    dc = next(s for s in signals if s.name == "DC 2.5 V")
    assert dc.attributes["Expected_RMS"] == "2.5"


# --- the File menu entry --------------------------------------------------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

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


def file_menu(window):
    # findChildren, not `action.menu()`: the latter hands back a temporary
    # wrapper that shiboken deletes while the generator is still running
    return next(m for m in window.menuBar().findChildren(QMenu)
                if m.title() == "&File")


def test_the_entry_sits_between_save_and_exit(window):
    """Where it was asked for, and where a user would look for it."""
    titles = [a.text() or ("|" if a.isSeparator() else "")
              for a in file_menu(window).actions()]

    assert "Create Demo Data ..." in titles
    assert titles.index("Save ...") < titles.index("Create Demo Data ...")
    assert titles.index("Create Demo Data ...") < titles.index("Exit")


def test_menu_entry_writes_the_datasets(window, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "spwb.gui.settings.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(
        "spwb.gui.time_processing.QMessageBox.information",
        lambda *a, **k: QMessageBox.Ok)

    window.create_demo_data()

    assert len(list(tmp_path.glob("*.h5"))) == DATASET_COUNT
    assert (tmp_path / "README.txt").is_file()


def test_cancelling_the_folder_dialog_writes_nothing(window, tmp_path,
                                                     monkeypatch):
    monkeypatch.setattr(
        "spwb.gui.settings.QFileDialog.getExistingDirectory",
        lambda *a, **k: "")

    window.create_demo_data()

    assert list(tmp_path.iterdir()) == []


def test_existing_demo_files_are_not_overwritten_without_consent(
        window, tmp_path, monkeypatch):
    """Answering No must leave what is already there untouched."""
    decoy = tmp_path / "04_FFT_Tones_known_amplitudes.h5"
    decoy.write_bytes(b"not really HDF5")

    monkeypatch.setattr(
        "spwb.gui.settings.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(tmp_path))
    asked = []
    monkeypatch.setattr(
        "spwb.gui.time_processing.QMessageBox.question",
        lambda *a, **k: asked.append(a) or QMessageBox.No)

    window.create_demo_data()

    assert asked, "overwriting existing demo files must be confirmed first"
    assert decoy.read_bytes() == b"not really HDF5"
    assert list(tmp_path.iterdir()) == [decoy]


def test_failure_reports_rather_than_raises(window, tmp_path, monkeypatch):
    """A write that fails must explain itself, not throw a traceback."""
    monkeypatch.setattr(
        "spwb.gui.settings.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(tmp_path))

    def explode(*args, **kwargs):
        raise OSError("disk is full")

    monkeypatch.setattr("spwb.demo.write_demo_data", explode)
    shown = []
    monkeypatch.setattr("spwb.gui.time_processing.QMessageBox.critical",
                        lambda *a, **k: shown.append(a))

    window.create_demo_data()          # must not raise

    assert shown, "a failure must be reported to the user"
    assert "disk is full" in " ".join(str(part) for part in shown[0])
