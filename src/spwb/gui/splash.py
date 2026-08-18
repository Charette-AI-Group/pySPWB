"""The splash screen, shown while the heavy imports happen.

Starting SPWB takes a couple of seconds, and almost none of it is Qt:
PySide6 costs about 0.24 s while pyqtgraph, numpy and scipy together cost
around 2.1 s, and all of those arrive with the first analysis window. So Qt
is up and able to draw long before there is anything to show, which is
exactly the gap a splash screen is for.

That only works if the window is imported *after* the splash is on screen -
see :func:`spwb.gui.app.main`. Importing it at module scope, as this
package did originally, spends the whole two seconds before any of our code
runs and leaves nothing to show it with.

Set ``SPWB_NO_SPLASH=1`` to skip it; the screenshot tooling and anyone who
finds it irritating can then start straight into the window.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QSplashScreen

from .. import app_config

__all__ = ["make_splash", "splash_disabled"]

#: the gold of the application icon, so the two are recognisably one thing
BACKGROUND_TOP = QColor("#FBBF24")
BACKGROUND_BOTTOM = QColor("#B45309")
TEXT = QColor("#12235C")
SUBTLE = QColor("#3B2E0B")

WIDTH, HEIGHT = 460, 240


def splash_disabled() -> bool:
    return os.environ.get("SPWB_NO_SPLASH", "") == "1"


def _artwork() -> QPixmap:
    """Drawn rather than loaded, so it needs no file beyond the icon."""
    from PySide6.QtGui import QLinearGradient

    pixmap = QPixmap(WIDTH, HEIGHT)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    gradient = QLinearGradient(0, 0, 0, HEIGHT)
    gradient.setColorAt(0.0, BACKGROUND_TOP)
    gradient.setColorAt(1.0, BACKGROUND_BOTTOM)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(0, 0, WIDTH, HEIGHT, 16, 16)

    icon = app_config.icon_file()
    if icon is not None:
        # QIcon, not QPixmap: a .ico holds seven sizes and QPixmap picks a
        # small one, which then has to be scaled *up* to 96 and turns to
        # mush. QIcon.pixmap chooses the best entry and scales down.
        from PySide6.QtGui import QIcon

        art = QIcon(str(icon)).pixmap(96, 96)
        if not art.isNull():
            painter.drawPixmap(28, (HEIGHT - art.height()) // 2 - 14, art)

    left = 148
    painter.setPen(TEXT)
    font = painter.font()
    font.setPointSize(20)
    font.setWeight(QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(left, 96, app_config.APP_NAME)

    font.setPointSize(11)
    font.setWeight(QFont.Weight.Normal)
    painter.setFont(font)
    painter.drawText(left, 122, app_config.APP_TITLE)

    painter.setPen(SUBTLE)
    font.setPointSize(9)
    painter.setFont(font)
    painter.drawText(left, 146, f"version {app_config.APP_VERSION}")
    painter.drawText(left, 164, app_config.ORGANIZATION_NAME)
    painter.end()
    return pixmap


def make_splash() -> QSplashScreen | None:
    """The splash, already shown, or ``None`` if it is switched off.

    Close it with ``splash.finish(window)``: that ties its lifetime to the
    window appearing, rather than to a timer that can outlive a slow start
    or vanish before one.
    """
    if splash_disabled():
        return None
    splash = QSplashScreen(_artwork())
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    splash.show()
    return splash


def report(splash: QSplashScreen | None, message: str) -> None:
    """Say what is happening, and let Qt actually paint it."""
    if splash is None:
        return
    splash.showMessage(f"   {message}",
                       Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                       TEXT)
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
