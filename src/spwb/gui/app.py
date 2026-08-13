"""Application entry point: ``python -m spwb``."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .bridge import WindowManager
from .time_processing import TimeProcessingWindow

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("SPWB")
    app.setOrganizationName("Charette AI Group")

    manager = WindowManager()
    window = TimeProcessingWindow(manager)
    window.show()

    # any file paths on the command line are loaded into the first window
    from ..processing.io import (
        read_hdf5,
        read_head_hdf,
        read_rpc,
        read_tdms,
        read_wave,
    )
    readers = {".h5": read_hdf5, ".hdf5": read_hdf5,
               ".tdms": read_tdms, ".wav": read_wave,
               ".rsp": read_rpc,
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
