import pathlib

import numpy as np
import pytest


@pytest.fixture(scope="session")
def lv():
    """LabVIEW 2022 ground-truth reference data (see tools/make_fixtures)."""
    path = pathlib.Path(__file__).parent / "fixtures" / "labview_reference.npz"
    return np.load(path)


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path_factory, monkeypatch):
    """Keep every test out of the developer's real application settings.

    The GUI tests drive real menu actions - ``open_hdf5``, ``save_wave`` -
    and those record the folder they were pointed at, while closing a window
    saves its geometry and column layout. Without this the suite would
    rewrite the remembered folders to pytest temp directories that are gone
    by the time the application next starts, and shuffle the window layout
    of whoever ran it.

    Autouse rather than opt-in: a test that forgets it would corrupt real
    settings silently and only on the machine that ran it, which is the
    worst failure to chase. Tests wanting their own store still declare the
    ``store`` fixture and simply override this one.
    """
    try:
        from PySide6.QtCore import QSettings
    except ImportError:            # the Qt-free half of the suite
        return

    from spwb.gui import settings

    ini = tmp_path_factory.mktemp("settings") / "spwb.ini"
    scratch = QSettings(str(ini), QSettings.IniFormat)
    monkeypatch.setattr(settings, "_store", lambda: scratch)
