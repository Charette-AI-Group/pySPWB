"""Enforce the processing/GUI boundary.

The contract: ``spwb.processing`` (and plain ``spwb``) must be fully usable
without Qt ever being imported - notebooks and scripts should never pay for,
or be broken by, the GUI stack. Each check runs in a fresh subprocess so
modules imported by other tests can't mask a violation.

If one of these tests fails, someone added a Qt import (direct or indirect)
to the processing side. Move that code to ``spwb.gui`` instead.
"""
import subprocess
import sys

import pytest

FORBIDDEN = ("PySide6", "PyQt5", "PyQt6", "pyqtgraph", "shiboken6")

CHECK = r"""
import sys
import {module} as m
loaded = [name for name in sys.modules
          if name.split(".")[0] in {forbidden!r}]
assert not loaded, f"importing {module} loaded GUI modules: {{loaded}}"
"""


def run_clean_import(module: str) -> None:
    code = CHECK.format(module=module, forbidden=FORBIDDEN)
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", [
    "spwb",
    "spwb.processing",
    "spwb.processing.model",
    "spwb.processing.dsp",
    "spwb.processing.dsp.spectral",
    "spwb.processing.dsp.windows",
    "spwb.processing.io",
    "spwb.processing.io.tdms",
])
def test_processing_side_never_imports_qt(module):
    run_clean_import(module)


def test_processing_source_has_no_qt_references():
    """Static check: no Qt names anywhere under src/spwb/processing."""
    from pathlib import Path

    import spwb.processing
    root = Path(spwb.processing.__file__).parent
    offenders = []
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for name in (*FORBIDDEN, "QtCore", "QtWidgets", "QtGui"):
            if name in text:
                offenders.append(f"{py.name}: {name}")
    assert not offenders, offenders


def test_gui_is_a_client_of_processing_not_the_reverse():
    """A full notebook-style workflow with the GUI stack made unimportable."""
    code = r"""
import sys
sys.modules["PySide6"] = None   # any Qt import now raises ImportError
sys.modules["pyqtgraph"] = None

import numpy as np
from spwb.processing import Signal, SignalStore
from spwb.processing.dsp import auto_power_spectrums

fs = 1024.0
t = np.arange(int(fs)) / fs
store = SignalStore()
sig = store.add(Signal("sine", 2.0 * np.sin(2 * np.pi * 128 * t), 1.0 / fs))
spec = auto_power_spectrums(sig, freq_resolution=1.0, window="hanning")
k = round(128.0 / spec.dt)
assert abs(spec.y[k] - 2.0) < 1e-9, spec.y[k]
print("ok")
"""
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
