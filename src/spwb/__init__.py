"""spwb - Signal Processing Work Bench (Python port of the SPWB LabVIEW app).

Two strictly separated sides:

* :mod:`spwb.processing` - model, DSP and file IO. Qt-free by contract;
  safe to use in scripts and notebooks without ever touching a GUI.
* :mod:`spwb.gui` - the PySide6 application built on top of it. This is
  the only package that may import Qt, and importing plain ``spwb`` never
  pulls it in.

The two most-used classes are re-exported here for convenience::

    from spwb import Signal, SignalStore
"""
from .processing import Signal, SignalStore

__version__ = "1.0.0"
__all__ = ["Signal", "SignalStore"]
