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
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__

__all__ = ["DONATE_URL", "AboutDialog", "about_html", "show_about"]

APP_NAME = "Signal Processing Work Bench"
EDITOR = "Francois Charette, PhD"
#: the model that did the porting work, credited as CloakClip credits its own
AI_AGENT = "Claude - Opus 5"
COPYRIGHT_HOLDER = "Charette AI Group, LLC"

#: the PayPal button the SPWB README, the website and the other apps use
DONATE_URL = "https://www.paypal.com/donate/?hosted_button_id=FEM4WLD7LHY36"

REPO_URL = "https://github.com/Charette-AI-Group/pySPWB"
LABVIEW_REPO_URL = "https://github.com/Charette-AI-Group/SPWB"

# Dark text on yellow, matching CloakClip and the SAE Calculator so the
# button is recognisably the same one across the apps. Reads in either theme.
DONATE_COLOUR = "#f0b232"
DONATE_TEXT_COLOUR = "#1f1e1b"
DONATE_PRESSED_COLOUR = "#d9991f"

_DONATE_STYLE = f"""
    QPushButton {{
        background-color: {DONATE_COLOUR};
        color: {DONATE_TEXT_COLOUR};
        border: none;
        border-radius: 6px;
        padding: 6px 18px;
        font-weight: 600;
    }}
    QPushButton:hover, QPushButton:pressed {{
        background-color: {DONATE_PRESSED_COLOUR};
    }}
"""


def about_html(year: int | None = None) -> str:
    """The dialog's contents, as rich text."""
    year = datetime.date.today().year if year is None else year
    return (
        f"<h3>{APP_NAME}</h3>"
        f"<p>Python port, version {__version__}</p>"
        f"<p>Editor: {EDITOR}<br>"
        f"AI Agent: {AI_AGENT}</p>"
        f"<p>Ported from the original "
        f'<a href="{LABVIEW_REPO_URL}">LabVIEW application</a>; '
        f'the port lives at <a href="{REPO_URL}">pySPWB</a>. '
        f"Both are open source under the MIT licence.</p>"
        f"<p>&copy; {year} {COPYRIGHT_HOLDER}</p>"
    )


class AboutDialog(QDialog):
    """About, with a Donate button on the left and Close on the right."""

    def __init__(self, text: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About SPWB")
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
        QDesktopServices.openUrl(QUrl(DONATE_URL))
        return True
    return False
