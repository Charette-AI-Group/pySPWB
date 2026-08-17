"""Window icons, applied in one place.

Each analysis window carries artwork of what it shows, so a taskbar with
several SPWB windows open can be read without hovering. The files are drawn
by ``tools/make_icons.py`` into ``spwb/resources`` and located through
:mod:`spwb.app_config` - never by path, because a PyInstaller build reads
them from the extraction directory instead.

Applying an icon is one guarded line, but it is one guarded line in five
windows, which is exactly how four of them end up without it.
"""
from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget

from .. import app_config

__all__ = ["apply_window_icon"]


def apply_window_icon(window: QWidget, key: str) -> bool:
    """Give ``window`` the icon for its type; say whether there was one.

    Returns False when the icon has not been generated, having changed
    nothing - the application runs without icons rather than failing, which
    is the same contract ``app_config.icon_file`` has always had.
    """
    path = app_config.window_icon_file(key)
    if path is None:
        return False
    window.setWindowIcon(QIcon(str(path)))
    return True
