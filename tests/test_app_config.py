"""Application metadata, paths and the icon hook.

Two things here are worth a test rather than a comment: the module must
stay importable without Qt, since packaging scripts and the Qt-free half of
the library both read it; and the icon lookup must degrade to None so the
application runs before any icon exists.
"""
import subprocess
import sys

import pytest

from spwb import __version__, app_config


def test_it_imports_without_qt():
    """Packaging tools and spwb.processing both read this; neither wants Qt."""
    code = (
        "import sys, spwb.app_config as c;"
        "loaded=[m for m in sys.modules if m.split('.')[0] in "
        "('PySide6','shiboken6','pyqtgraph')];"
        "assert not loaded, loaded;"
        "print(c.APP_NAME)"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == app_config.APP_NAME


def test_the_version_is_not_duplicated():
    """One version, in spwb.__init__, mirrored here - never re-typed."""
    assert app_config.APP_VERSION == __version__


def test_identity_is_what_qsettings_keys_on():
    assert app_config.APP_NAME
    assert app_config.ORGANIZATION_NAME
    assert app_config.APP_TITLE != app_config.APP_NAME


def test_no_icon_yet_is_not_an_error():
    """The app must run before an icon exists, and pick one up when added."""
    assert app_config.icon_file() is None or app_config.ICON_FILE.is_file()


def test_the_icon_is_looked_up_afresh_each_time(tmp_path, monkeypatch):
    """So dropping a file into resources/ needs no code change."""
    fake = tmp_path / "spwb.ico"
    monkeypatch.setattr(app_config, "ICON_FILE", fake)
    assert app_config.icon_file() is None

    fake.write_bytes(b"not really an icon, but it exists")
    assert app_config.icon_file() == fake


def test_resources_live_inside_the_package():
    """They must ship in the wheel, so they cannot sit beside it."""
    package_root = app_config.RESOURCES_DIR.parent
    assert package_root.name == "spwb"
    assert (app_config.RESOURCES_DIR / "README.md").is_file()


def test_the_data_folder_is_per_user_and_named_for_the_app():
    assert app_config.APP_DATA_DIR.name == app_config.APP_NAME
    assert app_config.APP_DATA_DIR.parent != app_config.APP_DATA_DIR


@pytest.mark.parametrize("colour", ["DONATE_COLOUR", "DONATE_TEXT_COLOUR",
                                    "DONATE_PRESSED_COLOUR", "ACCENT_COLOUR"])
def test_brand_colours_are_hex(colour):
    value = getattr(app_config, colour)
    assert value.startswith("#") and len(value) == 7
    int(value[1:], 16)


def test_the_donate_link_is_the_projects_paypal_button():
    assert "FEM4WLD7LHY36" in app_config.DONATE_URL
