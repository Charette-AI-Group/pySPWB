"""spwb.processing - the complete Qt-free side of SPWB.

Everything a script or notebook needs lives under this package:

* :mod:`spwb.processing.model` - :class:`Signal` (the wForm) and
  :class:`SignalStore` (the shared registry)
* :mod:`spwb.processing.dsp`   - windows and spectral analysis
* :mod:`spwb.processing.io`    - file formats (TDMS, ...)

Importing anything under ``spwb.processing`` must never load Qt; the test
suite enforces this (``tests/test_separation.py``). The GUI in
:mod:`spwb.gui` is a *client* of this package, never the other way around.

Notebook quick start::

    from spwb.processing import Signal
    from spwb.processing.io import read_tdms
    from spwb.processing.dsp import auto_power_spectrums

    signals = read_tdms("run.tdms")
    spectrum = auto_power_spectrums(signals[0], freq_resolution=1.0,
                                    window="hanning")
"""
from .model.signal import Signal
from .model.store import SignalStore

__all__ = ["Signal", "SignalStore"]
