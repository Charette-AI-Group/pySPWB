"""The About dialog, and the application metadata it shows.

Modelled on the About dialog in CloakClip, the sibling Charette AI Group
application, so the two look like they come from the same place: the same
credits block, the same yellow Donate button, the same PayPal link the SPWB
README and the website already use.

A plain :class:`QDialog` rather than :func:`QMessageBox.about`, for the
reason CloakClip found: a message box places its buttons by *role*, and
which side a non-standard button lands on then varies with the platform
style. Donate belongs on the left, away from Close, on every platform.
"""
from __future__ import annotations

import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import app_config

__all__ = ["AboutDialog", "about_html", "add_help_menu", "open_manuals",
           "show_about"]

#: re-exported so callers need not reach past this module for the one URL
#: they care about
DONATE_URL = app_config.DONATE_URL

_DONATE_STYLE = f"""
    QPushButton {{
        background-color: {app_config.DONATE_COLOUR};
        color: {app_config.DONATE_TEXT_COLOUR};
        border: none;
        border-radius: 6px;
        padding: 6px 18px;
        font-weight: 600;
    }}
    QPushButton:hover, QPushButton:pressed {{
        background-color: {app_config.DONATE_PRESSED_COLOUR};
    }}
"""


def about_html(year: int | None = None) -> str:
    """The dialog's contents, as rich text."""
    year = datetime.date.today().year if year is None else year
    return (
        f"<h3>{app_config.APP_TITLE}</h3>"
        f"<p>Version {app_config.APP_VERSION}</p>"
        f"<p>Editor: {app_config.EDITOR}<br>"
        f"AI Agent: {app_config.AI_AGENT}</p>"
        f"<p>Ported from the original "
        f'<a href="{app_config.LABVIEW_REPO_URL}">LabVIEW application</a>; '
        f'the port lives at <a href="{app_config.REPO_URL}">pySPWB</a>. '
        f"Both are open source under the MIT licence.</p>"
        f"<p>&copy; {year} {app_config.COPYRIGHT_HOLDER}</p>"
    )


class AboutDialog(QDialog):
    """About, with a Donate button on the left and Close on the right."""

    def __init__(self, text: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {app_config.APP_NAME}")
        #: read back by the caller after ``exec`` rather than connected to
        #: the click, so the browser opens once this dialog has closed
        #: instead of behind it
        self.donate_requested = False

        layout = QVBoxLayout(self)

        self.about_label = QLabel(about_html() if text is None else text)
        self.about_label.setTextFormat(Qt.TextFormat.RichText)
        self.about_label.setMinimumWidth(440)
        self.about_label.setWordWrap(True)
        self.about_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        self.about_label.setOpenExternalLinks(True)
        layout.addWidget(self.about_label)
        layout.addSpacing(8)

        self.donate_button = QPushButton("Donate")
        self.donate_button.setStyleSheet(_DONATE_STYLE)
        self.donate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.donate_button.clicked.connect(self._on_donate)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        # Enter closes the dialog. It must never be the thing that opens a
        # payment page, which is why Donate gives up its auto-default.
        self.close_button.setDefault(True)
        self.close_button.setAutoDefault(True)
        self.donate_button.setAutoDefault(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.donate_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def _on_donate(self) -> None:
        self.donate_requested = True
        self.accept()


def show_about(parent: QWidget | None = None) -> bool:
    """Show the dialog; open the donation page if it was asked for.

    Returns whether the donation page was opened, so the caller can say so
    in its status bar.
    """
    dialog = AboutDialog(parent=parent)
    dialog.exec()
    if dialog.donate_requested:
        QDesktopServices.openUrl(QUrl(app_config.DONATE_URL))
        return True
    return False


def open_manuals(parent: QWidget | None = None,
                 manual: str | None = None) -> bool:
    """Open a manual in a browser; return whether one opened.

    ``manual`` is a file stem in ``docs/manuals``; without it the index is
    opened instead. The online copy rather than any local one - GitHub
    renders the markdown and the companion notebooks, while a checkout's .md
    would open in a text editor and a wheel install has no copy at all. If no
    browser can be launched the address is shown instead, because leaving the
    user with nothing is worse than making them copy a URL.
    """
    url = app_config.manual_url(manual)
    if QDesktopServices.openUrl(QUrl(url)):
        return True
    QMessageBox.information(
        parent, "User Manuals",
        f"Could not open a browser. The manuals are at:\n\n{url}")
    return False


def _report(window: QWidget, message: str) -> None:
    """Say something in the window's status bar, if it has one."""
    status_bar = getattr(window, "statusBar", None)
    if callable(status_bar):
        status_bar().showMessage(message)


def add_help_menu(window: QWidget, *, manual: str | None = None,
                  manual_title: str | None = None) -> QMenu:
    """Add the Help menu every SPWB window carries, and return it.

    Manuals first, About underneath: the manuals are what a new user needs,
    and nobody looks under About for documentation. Built here rather than
    in each window so the five windows cannot drift apart - they were
    written at different times and it would be easy to fix one and forget
    the rest.

    ``manual`` names this window's own page in ``docs/manuals`` and
    ``manual_title`` labels the entry, so F1 is *context-sensitive help* -
    it opens the manual for the window you are in, which is what F1 means
    everywhere else. The index stays one entry below for the times you want
    a different window's manual. A window that passes neither gets the index
    on F1.
    """
    def this_manual() -> None:
        if open_manuals(window, manual):
            _report(window, "The manual is opening in your browser.")

    def index() -> None:
        if open_manuals(window):
            _report(window, "The user manuals are opening in your browser.")

    def about() -> None:
        if show_about(window):
            _report(window,
                    "Thank you - the donation page is opening in your browser.")

    menu = window.menuBar().addMenu("&Help")
    if manual:
        action = QAction(f"{manual_title or 'This Window'} Manual", window)
        action.setShortcut(QKeySequence.HelpContents)   # F1
        action.triggered.connect(this_manual)
        menu.addAction(action)
        action = QAction("All User Manuals ...", window)
        action.triggered.connect(index)
        menu.addAction(action)
    else:
        action = QAction("User Manuals ...", window)
        action.setShortcut(QKeySequence.HelpContents)
        action.triggered.connect(index)
        menu.addAction(action)
    menu.addSeparator()
    action = QAction("About SPWB", window)
    action.triggered.connect(about)
    menu.addAction(action)
    return menu
