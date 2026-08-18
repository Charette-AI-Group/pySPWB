"""Console entry point.

Kept separate from :mod:`spwb.gui.app` so that ``spwb`` can give a useful
message when the GUI extra is not installed, instead of an import
traceback: ``pip install spwb`` is a perfectly reasonable thing to have
done, and the fix should be obvious from the error.

Two things arrive here rather than in ``gui.app``: that message, and
``--selftest``, which a packaged build runs to prove it is complete without
opening a window (see :mod:`spwb.selftest`).
"""
from __future__ import annotations

import sys

__all__ = ["main"]

_MISSING_GUI = """\
SPWB's desktop application needs the GUI extra, which is not installed.

    pip install "spwb[gui]"

The processing library works without it - if you only need the DSP and
file IO, import it directly and skip the application:

    from spwb.processing import Signal
    from spwb.processing.io import read_tdms
    from spwb.processing.dsp import auto_power_spectrums
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    # Ahead of the GUI import on purpose: spwb.selftest chooses its own Qt
    # platform, and it must be able to do that before anything creates a
    # QApplication. An optional path follows the flag because a windowed
    # build has no console for the report to go to.
    if "--selftest" in argv:
        position = argv.index("--selftest")
        report = argv[position + 1] if len(argv) > position + 1 else None
        from .selftest import main as run_selftest
        return run_selftest(report)

    try:
        from .gui.app import main as run_app
    except ImportError as exc:
        missing = getattr(exc, "name", "") or ""
        if missing.split(".")[0] in ("PySide6", "pyqtgraph", "shiboken6"):
            print(_MISSING_GUI, file=sys.stderr)
            return 1
        raise                      # a real import error, not the extra
    return run_app(argv)


if __name__ == "__main__":
    raise SystemExit(main())
