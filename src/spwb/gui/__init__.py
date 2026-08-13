"""Qt (PySide6) user interface for SPWB.

This is the only package in spwb allowed to import Qt, and it is a pure
client of :mod:`spwb.processing` - the boundary is enforced by
``tests/test_separation.py``. Importing this package requires the ``gui``
extra: ``pip install spwb[gui]``; everything under ``spwb.processing``
stays importable without it.
"""
from .app import main
from .bridge import StoreBridge, WindowManager
from .fft_analysis import FFTWindow
from .lms_analysis import LMSWindow
from .tf_analysis import TransferFunctionWindow
from .tfa_analysis import TimeFrequencyWindow
from .time_processing import TimeProcessingWindow

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
