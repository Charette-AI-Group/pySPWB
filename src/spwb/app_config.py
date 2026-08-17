"""Application metadata, paths and brand colours - in one place.

Everything here was previously scattered: the application and organisation
names in ``gui/app.py``, the credits and Donate colours in ``gui/about.py``,
the version in ``__init__``. Collecting them matters most for the things
that do not exist yet - an icon, a bundled build - because those need the
same handful of facts from several places at once.

**Qt-free on purpose.** Packaging scripts, the icon generator and CI all
want the app name and the resources directory without paying for PySide6,
and :mod:`spwb.processing` must never see Qt at all. Nothing here imports
it; the GUI turns :data:`ICON_FILE` into a ``QIcon`` itself.

Modelled on ``appConfig.py`` in CloakClip, the sibling Charette AI Group
application, so the two stay recognisably related.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import __version__

__all__ = [
    "ACCENT_COLOUR",
    "AI_AGENT",
    "APP_DATA_DIR",
    "APP_NAME",
    "APP_TITLE",
    "APP_VERSION",
    "COPYRIGHT_HOLDER",
    "DONATE_COLOUR",
    "DONATE_PRESSED_COLOUR",
    "DONATE_TEXT_COLOUR",
    "DONATE_URL",
    "EDITOR",
    "ICON_FILE",
    "LABVIEW_REPO_URL",
    "MANUALS_URL",
    "ORGANIZATION_NAME",
    "REPO_URL",
    "RESOURCES_DIR",
    "icon_file",
    "manual_url",
]

# -- identity --------------------------------------------------------------
#: short name: the QApplication name, the settings key, the data folder
APP_NAME = "SPWB"
#: what a human sees in a title bar or an About box
APP_TITLE = "Signal Processing Work Bench"
APP_VERSION = __version__
#: pairs with APP_NAME to place the settings; changing either moves them
ORGANIZATION_NAME = "Charette AI Group"

# -- credits ---------------------------------------------------------------
EDITOR = "Francois Charette, PhD"
#: the model that did the porting work, as CloakClip credits its own
AI_AGENT = "Claude - Opus 5"
COPYRIGHT_HOLDER = "Charette AI Group, LLC"

# -- links -----------------------------------------------------------------
#: the PayPal button the README, the website and the sibling apps all use
DONATE_URL = "https://www.paypal.com/donate/?hosted_button_id=FEM4WLD7LHY36"
REPO_URL = "https://github.com/Charette-AI-Group/pySPWB"
LABVIEW_REPO_URL = "https://github.com/Charette-AI-Group/SPWB"
#: the user manuals, one per analysis window. Deliberately the GitHub URL
#: and not a copy inside the checkout: GitHub renders the markdown and the
#: companion notebooks, a local .md would open in a text editor, and most
#: users install the wheel and have no local copy at all.
MANUALS_URL = f"{REPO_URL}/tree/main/docs/manuals"


def manual_url(name: str | None = None) -> str:
    """The URL of one manual, or of the index when ``name`` is None.

    ``name`` is the file's stem in ``docs/manuals`` - "fft-analysis" and so
    on - so each window can ask for its own page and F1 lands on the manual
    for the window you are actually in.
    """
    if not name:
        return MANUALS_URL
    return f"{REPO_URL}/blob/main/docs/manuals/{name}.md"


# -- brand colours ---------------------------------------------------------
# Dark text on yellow, matching CloakClip and the SAE Calculator so the
# Donate button is recognisably the same one across the apps. Legible in
# either theme, which is why it is a fixed colour rather than a palette role.
DONATE_COLOUR = "#f0b232"
DONATE_TEXT_COLOUR = "#1f1e1b"
DONATE_PRESSED_COLOUR = "#d9991f"
#: used sparingly for emphasis; readable on light and dark Windows themes
ACCENT_COLOUR = "#6366F1"


# -- paths -----------------------------------------------------------------
def _app_data_base() -> Path:
    """Where this OS keeps per-user application data."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home())))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))


PROJECT_ROOT = Path(__file__).resolve().parents[2]

# In a PyInstaller build the package lives inside an archive rather than on
# disk, so bundled files come from the extraction directory instead. Getting
# this wrong is the classic "works from source, no icon in the .exe" bug.
if getattr(sys, "frozen", False):
    RESOURCES_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) / "resources"
else:
    RESOURCES_DIR = Path(__file__).resolve().parent / "resources"

#: macOS has no use for .ico. Neither file has been made yet - see
#: ``src/spwb/resources/README.md``; :func:`icon_file` returns ``None``
#: until one exists, so the application simply runs without an icon.
ICON_FILE = RESOURCES_DIR / ("spwb.png" if sys.platform == "darwin"
                             else "spwb.ico")

APP_DATA_DIR = _app_data_base() / APP_NAME


def icon_file() -> Path | None:
    """The application icon, or ``None`` if it has not been added yet."""
    return ICON_FILE if ICON_FILE.is_file() else None
