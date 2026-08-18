"""Application entry point: ``python -m spwb``.

The order here is deliberate. Qt costs about 0.24 s to import while the
first analysis window drags in pyqtgraph, numpy and scipy for another
2.1 s, so the splash goes up first and the window is imported afterwards.
Importing it at module scope - as this file used to - spends the whole two
seconds before ``main`` runs and leaves nothing to put on screen.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import app_config
from . import splash as splash_module
from .bridge import WindowManager

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(app_config.APP_NAME)
    app.setOrganizationName(app_config.ORGANIZATION_NAME)
    app.setApplicationVersion(app_config.APP_VERSION)
    if (icon := app_config.icon_file()) is not None:
        app.setWindowIcon(QIcon(str(icon)))

    # Up now, while Qt is the only thing loaded, and covering the import
    # below - which is where the wait actually is.
    splash = splash_module.make_splash()
    splash_module.report(splash, "Loading signal processing ...")

    from .time_processing import TimeProcessingWindow

    splash_module.report(splash, "Starting ...")
    manager = WindowManager()
    window = TimeProcessingWindow(manager)
    window.show()
    if splash is not None:
        # tied to the window appearing rather than to a timer, so a slow
        # machine never shows a splash floating over a live application
        splash.finish(window)

    # any file paths on the command line are loaded into the first window
    from ..processing.io import (
        read_hdf5,
        read_head_hdf,
        read_rpc,
        read_tdms,
        read_text,
        read_wave,
    )
    readers = {".h5": read_hdf5, ".hdf5": read_hdf5,
               ".tdms": read_tdms, ".wav": read_wave,
               ".rsp": read_rpc,
               ".csv": read_text, ".txt": read_text,
               # HEAD acoustics, not HDF5 - see io/head_hdf.py
               ".hdf": read_head_hdf}
    for path in argv[1:]:
        reader = readers.get(Path(path).suffix.lower())
        if reader is None:
            continue
        try:
            for sig in reader(path):
                window.store.add(sig)
        except Exception as exc:  # pragma: no cover - CLI convenience
            print(f"could not load {path}: {exc}", file=sys.stderr)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
