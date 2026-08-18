# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for the standalone SPWB application.

    python -m PyInstaller spwb.spec --noconfirm

Output: ``dist/SPWB/SPWB.exe`` on Windows and Linux, ``dist/SPWB.app`` on
macOS. Built and published by .github/workflows/build.yml; this file is the
whole recipe, so a local build and a CI build are the same build.

**A directory, not a single file.** PyInstaller's one-file mode unpacks the
entire bundle into a temporary folder on every launch, and this bundle is
large - PySide6, numpy, scipy and h5py, a few hundred MB. That is ten to
twenty seconds of nothing on screen each time the user starts SPWB, and it
would waste the lazy-import work in ``spwb/gui/__init__.py`` that exists to
get the splash screen up in the first place. The directory is zipped for
distribution instead, so the download is still one file.

**The GUI stack is trimmed, the numerics are not.** Qt's Addons - WebEngine
alone is bigger than everything SPWB uses - are excluded by name; only
QtCore, QtGui and QtWidgets are imported anywhere in ``src``. Nothing under
numpy or scipy is excluded: which submodules the DSP reaches is not obvious
from the imports, and a spectrum that fails on a user's machine is a far
worse trade than a hundred megabytes. ``spwb --selftest`` runs against the
result and checks the numbers really do come out right.
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)                                          # noqa: F821

# app_config is Qt-free precisely so packaging can read it - see its docstring
sys.path.insert(0, str(ROOT / "src"))
from spwb import app_config                                    # noqa: E402

# PyInstaller converts the PNG to .icns at build time (needs Pillow, which
# the "build" extra installs). Windows and Linux take the multi-size .ico.
ICON = str(app_config.RESOURCES_DIR /
           ("spwb.png" if sys.platform == "darwin" else "spwb.ico"))

# spwb/gui/__init__.py resolves the window classes through import_module()
# on a table of strings, which static analysis cannot follow - without this
# the analysis windows would simply not be in the bundle. Collecting our own
# package wholesale costs nothing and removes the whole class of problem.
HIDDEN_IMPORTS = collect_submodules("spwb")

EXCLUDES = [
    # -- Qt Addons: none of this is imported anywhere under src/ ------------
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtUiTools", "PySide6.QtHelp",
    "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSensors", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtNetwork", "PySide6.QtNetworkAuth",
    # Deliberately NOT excluded: QtSvg and QtOpenGLWidgets. pyqtgraph guards
    # both behind FailedImport so their absence would not crash - it would
    # quietly disable a plot's right-click Export. They are small.
    # QtDBus stays too: the Linux platform theme uses it.

    # -- other bindings, so pyqtgraph cannot bind to one of them ------------
    "PyQt5", "PyQt6", "PySide2",

    # -- development and documentation tooling ------------------------------
    # matplotlib is in the dev extra for examples/ and jupytext et al. in
    # docs; all of them are usually installed in a build environment and
    # none belong in the application.
    "matplotlib", "IPython", "ipykernel", "jupytext", "nbformat", "nbclient",
    "notebook", "pytest", "ruff", "PIL", "tkinter", "sphinx",
    # unittest, pydoc and doctest look like obvious dead weight in a
    # measurement application and are deliberately NOT excluded: numpy
    # reaches unittest through numpy.testing, and pydoc arrives with the
    # widget stack. Excluding them builds perfectly cleanly and then fails
    # --selftest with ModuleNotFoundError at the first spectrum, which is
    # precisely the kind of silent breakage the self-test exists to catch.
]

a = Analysis(                                                  # noqa: F821
    [str(ROOT / "tools" / "standalone_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    # app_config points RESOURCES_DIR at _MEIPASS/resources when frozen, so
    # the icons must land in a folder of exactly that name.
    datas=[(str(app_config.RESOURCES_DIR), "resources")],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)                                              # noqa: F821

exe = EXE(                                                     # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # onedir: the rest goes in COLLECT
    name=app_config.APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=False: SPWB is a windowed application, so a build that opened
    # a terminal behind it would look broken. It also means sys.stdout is
    # None at runtime, which is why --selftest writes to a file.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(                                                # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=app_config.APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(                                              # noqa: F821
        coll,
        name=f"{app_config.APP_NAME}.app",
        icon=ICON,
        bundle_identifier="com.charette-ai-group.spwb",
        version=app_config.APP_VERSION,
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleName": app_config.APP_NAME,
            "CFBundleDisplayName": app_config.APP_TITLE,
            "CFBundleShortVersionString": app_config.APP_VERSION,
        },
    )
