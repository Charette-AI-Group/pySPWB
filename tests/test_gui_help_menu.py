"""The Help menu, which every SPWB window carries.

The original LabVIEW runtime menu ended in "About". Once there were user
manuals to point at, that menu became "Help" - nobody looks under About for
documentation - and it was given to the four analysis windows as well as
the hub, so a user who is deep in an FFT window can reach the documentation
without going back.

It is built once, in ``spwb.gui.about.add_help_menu``. These tests run
against every window precisely because five copies would have drifted.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QMenu

from spwb import app_config
from spwb.gui.bridge import WindowManager


def window_classes():
    from spwb.gui.fft_analysis import FFTWindow
    from spwb.gui.lms_analysis import LMSWindow
    from spwb.gui.tf_analysis import TransferFunctionWindow
    from spwb.gui.tfa_analysis import TimeFrequencyWindow
    from spwb.gui.time_processing import TimeProcessingWindow

    return {
        "TimeProcessing": TimeProcessingWindow,
        "FFT": FFTWindow,
        "TransferFunction": TransferFunctionWindow,
        "TimeFrequency": TimeFrequencyWindow,
        "LMS": LMSWindow,
    }


WINDOWS = list(window_classes())


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=WINDOWS)
def window(qapp, request):
    """Each of the five windows in turn, so none can drift from the rest."""
    w = window_classes()[request.param](WindowManager())
    yield w
    w.close()


def help_menu(window):
    # findChildren, not `action.menu()`: the latter hands back a temporary
    # wrapper that shiboken deletes while the generator is still running
    menus = [m for m in window.menuBar().findChildren(QMenu)
             if m.title() == "&Help"]
    assert menus, f"{type(window).__name__} has no Help menu"
    return menus[0]


def entries(window):
    return [a.text() for a in help_menu(window).actions() if a.text()]


def trigger(window, text):
    """Fire a Help entry the way a click would, rather than calling a method.

    The handlers are closures created by add_help_menu, so going through the
    action is the only way to exercise what the user actually gets.
    """
    for action in help_menu(window).actions():
        if action.text() == text:
            action.trigger()
            return
    raise AssertionError(f"no Help entry {text!r}; has {entries(window)}")


def test_every_window_has_a_help_menu_and_no_about_menu(window):
    titles = [m.title() for m in window.menuBar().findChildren(QMenu)]

    assert "&Help" in titles
    assert "&About" not in titles


def test_help_is_the_last_menu(window):
    """Where every desktop application puts it."""
    top_level = [a.text() for a in window.menuBar().actions()]

    assert top_level[-1] == "&Help"


def test_manuals_come_first_and_about_stays_underneath(window):
    assert entries(window) == ["User Manuals ...", "About SPWB"]


def test_the_manuals_entry_opens_the_rendered_manuals(window, monkeypatch):
    opened = []
    monkeypatch.setattr("spwb.gui.about.QDesktopServices.openUrl",
                        lambda url: opened.append(url.toString()) or True)

    trigger(window, "User Manuals ...")

    assert opened == [app_config.MANUALS_URL]
    # the GitHub copy, because that is what renders the markdown and the
    # companion notebooks rather than offering them as downloads
    assert opened[0].startswith("https://github.com/")
    assert "docs/manuals" in opened[0]


def test_a_browser_that_will_not_open_still_shows_the_address(window,
                                                              monkeypatch):
    """Telling the user nothing would leave them with no way to the docs."""
    monkeypatch.setattr("spwb.gui.about.QDesktopServices.openUrl",
                        lambda url: False)
    shown = []
    monkeypatch.setattr("spwb.gui.about.QMessageBox.information",
                        lambda *a, **k: shown.append(a))

    trigger(window, "User Manuals ...")

    assert shown, "a failed launch must still give the user the URL"
    assert app_config.MANUALS_URL in " ".join(str(part) for part in shown[0])


def test_the_about_entry_opens_the_dialog(window, monkeypatch):
    seen = []
    monkeypatch.setattr("spwb.gui.about.show_about",
                        lambda parent=None: seen.append(parent) or False)

    trigger(window, "About SPWB")

    assert seen == [window], "the dialog must be parented to the window"


def test_a_donation_is_acknowledged_in_the_status_bar(window, monkeypatch):
    monkeypatch.setattr("spwb.gui.about.show_about", lambda parent=None: True)

    trigger(window, "About SPWB")

    assert "Thank you" in window.statusBar().currentMessage()


def test_the_manuals_url_is_the_folder_github_renders():
    """A tree URL, not a blob: it lists the manuals and renders the index."""
    assert app_config.MANUALS_URL.startswith(app_config.REPO_URL)
    assert "/tree/" in app_config.MANUALS_URL
    assert app_config.MANUALS_URL.endswith("docs/manuals")
