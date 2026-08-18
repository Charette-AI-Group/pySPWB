"""The splash screen, and the import order that makes it worth having.

Starting SPWB is dominated by pyqtgraph, numpy and scipy - about 2.1 s
against Qt's 0.24 s - so the splash can only cover the wait if the window
is imported *after* it is on screen. That ordering is the whole feature and
is easy to undo by moving one import back to the top of app.py, so it is
pinned here.
"""
import ast
import os
import pathlib
import subprocess
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QSplashScreen

from spwb import app_config
from spwb.gui import splash as splash_module

APP_SOURCE = pathlib.Path(splash_module.__file__).with_name("app.py")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def splash_on(monkeypatch):
    monkeypatch.delenv("SPWB_NO_SPLASH", raising=False)


# -- the artwork ------------------------------------------------------------
def test_the_splash_is_drawn_and_shown(qapp, splash_on):
    splash = splash_module.make_splash()
    try:
        assert isinstance(splash, QSplashScreen)
        assert splash.isVisible()
        pixmap = splash.pixmap()
        assert not pixmap.isNull()
        assert (pixmap.width(), pixmap.height()) == (splash_module.WIDTH,
                                                     splash_module.HEIGHT)
    finally:
        splash.close()


def test_it_can_be_switched_off(qapp, monkeypatch):
    """An escape hatch for tooling, and for anyone who dislikes it."""
    monkeypatch.setenv("SPWB_NO_SPLASH", "1")

    assert splash_module.splash_disabled() is True
    assert splash_module.make_splash() is None


def test_reporting_progress_survives_no_splash(qapp, monkeypatch):
    monkeypatch.setenv("SPWB_NO_SPLASH", "1")

    splash_module.report(None, "anything")      # must not raise


def test_progress_messages_reach_the_splash(qapp, splash_on):
    splash = splash_module.make_splash()
    try:
        splash_module.report(splash, "Loading signal processing ...")

        assert "Loading signal processing" in splash.message()
    finally:
        splash.close()


# -- the ordering that makes it work ----------------------------------------
def _module_level_imports(source: pathlib.Path) -> set[str]:
    """Everything app.py imports before main() is ever called."""
    tree = ast.parse(source.read_text(encoding="utf8"))
    names = set()
    for node in tree.body:                     # module level only
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_the_window_is_not_imported_before_the_splash_can_show():
    """The point of the feature: importing time_processing at module scope
    spends the whole 2.1 s before main() runs, with nothing on screen."""
    at_module_level = _module_level_imports(APP_SOURCE)

    assert not any("time_processing" in name for name in at_module_level), (
        "app.py imports the window at module scope again - the splash "
        "cannot appear until that import finishes")
    assert not any("pyqtgraph" in name for name in at_module_level)


def test_the_splash_module_itself_stays_cheap():
    """It must not drag in what it exists to wait for."""
    at_module_level = _module_level_imports(
        pathlib.Path(splash_module.__file__))

    assert not any(heavy in name for name in at_module_level
                   for heavy in ("pyqtgraph", "numpy", "scipy",
                                 "time_processing"))


def test_main_shows_the_splash_then_finishes_it(qapp, splash_on, monkeypatch):
    """finish(window) is what ties the splash's life to the window's.

    A timer would be wrong in both directions: too short on a slow machine
    and the splash vanishes early, too long and it floats over a live app.
    """
    from spwb.gui import app as app_module

    events = []
    real_make = splash_module.make_splash

    def spy_make():
        splash = real_make()
        events.append("shown")
        original_finish = splash.finish

        def finish(window):
            events.append("finished")
            original_finish(window)

        splash.finish = finish
        return splash

    monkeypatch.setattr(app_module.splash_module, "make_splash", spy_make)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)

    assert app_module.main(["spwb"]) == 0
    assert events == ["shown", "finished"]


def test_the_splash_carries_the_application_identity(qapp, splash_on):
    """Drawn from app_config, so a version bump needs no artwork change."""
    source = pathlib.Path(splash_module.__file__).read_text(encoding="utf8")

    for attribute in ("APP_NAME", "APP_TITLE", "APP_VERSION",
                      "ORGANIZATION_NAME"):
        assert f"app_config.{attribute}" in source
    assert app_config.icon_file() is not None, "the splash shows the icon"


def test_importing_the_gui_package_does_not_load_the_heavy_stack():
    """The regression that made the first version of this feature useless.

    spwb/gui/__init__.py used to name all five window classes eagerly, so
    importing *anything* from spwb.gui - the splash included - pulled
    pyqtgraph and scipy first. Deferring the window import inside app.py
    achieved nothing while that stood: the splash appeared at 3.21 s and
    the window at 3.24 s, covering 1% of the wait. With the package lazy it
    appears at 1.4 s and covers over half.

    Run in a clean subprocess, because by the time this file's other tests
    have run the modules are already imported.
    """
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; import spwb.gui; "
         "print(','.join(m for m in ('pyqtgraph', 'scipy') "
         "if m in sys.modules))"],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})

    assert result.returncode == 0, result.stderr
    loaded = result.stdout.strip()
    assert not loaded, (
        f"importing spwb.gui pulled in {loaded} - the splash cannot appear "
        "until that finishes. Keep spwb/gui/__init__.py lazy.")


def test_the_lazy_package_still_exports_every_window():
    """PEP 562 must not quietly drop a name from the public API."""
    import spwb.gui

    for name in spwb.gui.__all__:
        assert getattr(spwb.gui, name) is not None
    assert sorted(dir(spwb.gui)) == sorted(spwb.gui.__all__)
    with pytest.raises(AttributeError, match="has no attribute"):
        _ = spwb.gui.NotAWindow
