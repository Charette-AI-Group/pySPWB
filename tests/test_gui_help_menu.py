"""The Help menu: the manuals first, About underneath.

The original LabVIEW runtime menu ended in "About". Once there were user
manuals to point at, that menu became "Help" - nobody looks under About for
documentation - and this pins the arrangement so a later edit cannot
quietly lose either entry.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QMenu

from spwb import app_config
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


def menu_titles(window):
    # findChildren, not `action.menu()`: the latter hands back a temporary
    # wrapper that shiboken deletes while the generator is still running
    return [m.title() for m in window.menuBar().findChildren(QMenu)]


def help_menu(window):
    return next(m for m in window.menuBar().findChildren(QMenu)
                if m.title() == "&Help")


def test_the_menu_is_called_help_not_about(window):
    titles = menu_titles(window)

    assert "&Help" in titles
    assert "&About" not in titles


def test_help_is_the_last_menu(window):
    """Where every desktop application puts it."""
    top_level = [a.text() for a in window.menuBar().actions()]

    assert top_level[-1] == "&Help"


def test_manuals_come_first_and_about_stays_underneath(window):
    entries = [a.text() for a in help_menu(window).actions() if a.text()]

    assert entries == ["User Manuals ...", "About SPWB"]


def test_manuals_entry_opens_the_rendered_manuals(window, monkeypatch):
    opened = []
    monkeypatch.setattr(
        "spwb.gui.time_processing.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()) or True)

    window.open_manuals()

    assert opened == [app_config.MANUALS_URL]
    # the GitHub copy, because that is the one that renders the markdown
    # and the companion notebooks rather than offering them as downloads
    assert opened[0].startswith("https://github.com/")
    assert "docs/manuals" in opened[0]


def test_a_browser_that_will_not_open_still_shows_the_address(window,
                                                              monkeypatch):
    """Telling the user nothing would leave them with no way to the docs."""
    monkeypatch.setattr(
        "spwb.gui.time_processing.QDesktopServices.openUrl",
        lambda url: False)
    shown = []
    monkeypatch.setattr("spwb.gui.time_processing.QMessageBox.information",
                        lambda *a, **k: shown.append(a))

    window.open_manuals()

    assert shown, "a failed launch must still give the user the URL"
    assert app_config.MANUALS_URL in " ".join(str(p) for p in shown[0])
