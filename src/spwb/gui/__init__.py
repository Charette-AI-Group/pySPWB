"""Qt (PySide6) user interface for SPWB.

This is the only package in spwb allowed to import Qt, and it is a pure
client of :mod:`spwb.processing` - the boundary is enforced by
``tests/test_separation.py``. Importing this package requires the ``gui``
extra: ``pip install spwb[gui]``; everything under ``spwb.processing``
stays importable without it.

**The window classes are resolved on first use, not on import.** Naming
them here eagerly cost 2.3 s before any of our code ran - pyqtgraph, numpy
and scipy all arrive with the first window - which is time the application
spent with nothing on screen, and which the splash screen could not cover
because it could not be shown until the import finished. ``__getattr__``
(PEP 562) keeps ``from spwb.gui import FFTWindow`` working exactly as
before while charging for it only when it is asked for.
"""
from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

#: public name -> the module that defines it
_EXPORTS = {
    "main": ".app",
    "StoreBridge": ".bridge",
    "WindowManager": ".bridge",
    "FFTWindow": ".fft_analysis",
    "LMSWindow": ".lms_analysis",
    "TransferFunctionWindow": ".tf_analysis",
    "TimeFrequencyWindow": ".tfa_analysis",
    "TimeProcessingWindow": ".time_processing",
}

__all__ = [
    "FFTWindow",
    "LMSWindow",
    "StoreBridge",
    "TimeFrequencyWindow",
    "TimeProcessingWindow",
    "TransferFunctionWindow",
    "WindowManager",
    "main",
]

if TYPE_CHECKING:                      # so type checkers and IDEs still see them
    from .app import main
    from .bridge import StoreBridge, WindowManager
    from .fft_analysis import FFTWindow
    from .lms_analysis import LMSWindow
    from .tf_analysis import TransferFunctionWindow
    from .tfa_analysis import TimeFrequencyWindow
    from .time_processing import TimeProcessingWindow


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value            # resolved once, then it is just a global
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
