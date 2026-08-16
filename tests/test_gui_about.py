"""The About dialog, matching CloakClip's.

The behaviours worth pinning are the two that are easy to get wrong and
awkward when they are: Enter must close the dialog rather than open a
payment page, and the browser must not be launched from behind a dialog
that is still up.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from spwb.gui import about


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_the_text_carries_the_credits_and_version(qapp):
    from spwb import __version__

    html = about.about_html(2026)

    assert about.APP_NAME in html
    assert __version__ in html
    assert about.EDITOR in html
    assert about.AI_AGENT in html
    assert "2026" in html
    assert about.COPYRIGHT_HOLDER in html
    assert "MIT" in html


def test_both_repositories_are_linked(qapp):
    html = about.about_html()

    assert f'href="{about.REPO_URL}"' in html
    assert f'href="{about.LABVIEW_REPO_URL}"' in html


def test_donate_uses_the_same_paypal_button_as_the_readme(qapp):
    assert "FEM4WLD7LHY36" in about.DONATE_URL


def test_enter_closes_rather_than_donating(qapp):
    """The default button is the one Enter presses - it must be Close."""
    dialog = about.AboutDialog()
    try:
        assert dialog.close_button.isDefault()
        assert dialog.close_button.autoDefault()
        assert not dialog.donate_button.autoDefault()
    finally:
        dialog.close()


def test_donating_records_the_request_instead_of_opening_at_once(qapp):
    """The browser is opened by the caller after exec returns, so the page
    cannot appear behind a dialog that is still on screen."""
    dialog = about.AboutDialog()
    try:
        assert dialog.donate_requested is False

        dialog.donate_button.click()

        assert dialog.donate_requested is True
    finally:
        dialog.close()


def test_closing_does_not_request_a_donation(qapp):
    dialog = about.AboutDialog()
    try:
        dialog.close_button.click()
        assert dialog.donate_requested is False
    finally:
        dialog.close()


def test_links_are_clickable(qapp):
    dialog = about.AboutDialog()
    try:
        assert dialog.about_label.openExternalLinks()
    finally:
        dialog.close()


def test_show_about_reports_whether_the_page_was_opened(qapp, monkeypatch):
    opened = []
    monkeypatch.setattr(about.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toString())))

    monkeypatch.setattr(about.AboutDialog, "exec", lambda self: None)
    assert about.show_about() is False
    assert not opened

    def donate_then_close(self):
        self.donate_requested = True

    monkeypatch.setattr(about.AboutDialog, "exec", donate_then_close)
    assert about.show_about() is True
    assert opened == [about.DONATE_URL]


def test_the_window_menu_opens_it_and_thanks_the_user(qapp, monkeypatch):
    pytest.importorskip("pyqtgraph")
    from spwb.gui.bridge import WindowManager
    from spwb.gui.time_processing import TimeProcessingWindow

    window = TimeProcessingWindow(WindowManager())
    try:
        monkeypatch.setattr(about, "show_about", lambda parent=None: True)
        window.show_about()
        assert "Thank you" in window.statusBar().currentMessage()
    finally:
        window.close()
