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
import pathlib

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

#: which manual each window's F1 must open, and what the entry is called.
#: Stated here independently of the source so a window pointed at the wrong
#: page fails rather than agreeing with itself.
OWN_MANUAL = {
    "TimeProcessing": ("time-processing", "Time Processing Manual"),
    "FFT": ("fft-analysis", "FFT Analysis Manual"),
    "TransferFunction": ("transfer-function", "Transfer Function Manual"),
    "TimeFrequency": ("time-frequency", "Time-Frequency Manual"),
    "LMS": ("adaptive-filtering", "Adaptive Filtering Manual"),
}


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=WINDOWS)
def window(qapp, request):
    """Each of the five windows in turn, so none can drift from the rest."""
    w = window_classes()[request.param](WindowManager())
    w.expected_manual = OWN_MANUAL[request.param]
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


def test_this_windows_manual_comes_first_then_the_index_then_about(window):
    _stem, label = window.expected_manual

    assert entries(window) == [label, "All User Manuals ...", "About SPWB"]


def test_f1_is_on_this_windows_own_manual(window):
    """Context-sensitive help: F1 means "help about *this*" everywhere."""
    _stem, label = window.expected_manual
    shortcuts = {a.text(): a.shortcut().toString()
                 for a in help_menu(window).actions() if a.text()}

    assert shortcuts[label] == "F1"
    assert shortcuts["All User Manuals ..."] == ""


def test_the_manual_entry_opens_this_windows_own_page(window, monkeypatch):
    stem, label = window.expected_manual
    opened = []
    monkeypatch.setattr("spwb.gui.about.QDesktopServices.openUrl",
                        lambda url: opened.append(url.toString()) or True)

    trigger(window, label)

    assert opened == [app_config.manual_url(stem)]
    # a blob URL, which is the page GitHub renders as a document
    assert opened[0] == f"{app_config.REPO_URL}/blob/main/docs/manuals/{stem}.md"


def test_the_index_entry_still_reaches_every_manual(window, monkeypatch):
    """The other four manuals stay one entry away."""
    opened = []
    monkeypatch.setattr("spwb.gui.about.QDesktopServices.openUrl",
                        lambda url: opened.append(url.toString()) or True)

    trigger(window, "All User Manuals ...")

    assert opened == [app_config.MANUALS_URL]


def test_a_browser_that_will_not_open_still_shows_the_address(window,
                                                              monkeypatch):
    """Telling the user nothing would leave them with no way to the docs."""
    stem, label = window.expected_manual
    monkeypatch.setattr("spwb.gui.about.QDesktopServices.openUrl",
                        lambda url: False)
    shown = []
    monkeypatch.setattr("spwb.gui.about.QMessageBox.information",
                        lambda *a, **k: shown.append(a))

    trigger(window, label)

    assert shown, "a failed launch must still give the user the URL"
    assert app_config.manual_url(stem) in " ".join(str(p) for p in shown[0])


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


def test_the_index_url_is_the_folder_github_renders():
    """A tree URL, not a blob: it lists the manuals and renders the index."""
    assert app_config.MANUALS_URL.startswith(app_config.REPO_URL)
    assert "/tree/" in app_config.MANUALS_URL
    assert app_config.MANUALS_URL.endswith("docs/manuals")
    assert app_config.manual_url() == app_config.MANUALS_URL
    assert app_config.manual_url(None) == app_config.MANUALS_URL


def test_every_window_points_at_a_manual_that_exists():
    """The URLs are built from a stem, so a typo would 404 in a browser and
    nowhere else. Check each one against the repository's own files."""
    manuals = pathlib.Path(__file__).resolve().parents[1] / "docs" / "manuals"
    if not manuals.is_dir():                  # installed copy, not a checkout
        pytest.skip("no docs/manuals in this tree")

    for key, (stem, _label) in OWN_MANUAL.items():
        assert (manuals / f"{stem}.md").is_file(), f"{key} -> {stem}.md missing"


def test_the_five_windows_point_at_five_different_manuals():
    stems = [stem for stem, _label in OWN_MANUAL.values()]

    assert len(set(stems)) == len(WINDOWS) == 5
