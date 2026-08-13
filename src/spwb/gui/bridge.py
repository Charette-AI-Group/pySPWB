"""Qt bridge for the GUI-free core.

:class:`spwb.SignalStore` deliberately knows nothing about Qt so the core
library stays usable from scripts and notebooks. This module adapts a store
to Qt's signal/slot world, and adds the window registry that replaces
SPWB's LabVIEW VI-server plumbing (``Launch NEW Window.vi``,
``Get - Window Name Index.vi``, ``GetClass - Window Info.vi``).
"""
from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import QObject
from PySide6.QtCore import Signal as QtSignal

from ..processing.model.signal import Signal
from ..processing.model.store import SignalStore

__all__ = ["StoreBridge", "WindowManager"]


class StoreBridge(QObject):
    """Re-emits :class:`SignalStore` events as Qt signals."""

    signal_added = QtSignal(object)
    signal_updated = QtSignal(object)
    signal_removed = QtSignal(object)
    changed = QtSignal()

    def __init__(self, store: SignalStore | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store if store is not None else SignalStore()
        self._unsubscribe = self.store.subscribe(self._on_event)

    def _on_event(self, event: str, signal: Signal) -> None:
        {"added": self.signal_added,
         "updated": self.signal_updated,
         "removed": self.signal_removed}[event].emit(signal)
        self.changed.emit()

    def close(self) -> None:
        self._unsubscribe()


class WindowManager(QObject):
    """Registry of open tool windows.

    In SPWB each GUI was a clone of a ``.vit`` template named
    ``"<type> <nn>"`` (``TFA 00``, ``TDP 01``, ...) and windows found each
    other through the VI server. Here they are plain Python objects in one
    process, so the registry is a list and sharing is a direct call.
    """

    windows_changed = QtSignal()

    #: window-type prefixes, matching the LabVIEW template names
    PREFIXES: ClassVar[dict[str, str]] = {
        "TimeProcessingWindow": "TDP",
        "FFTWindow": "FFT",
        "TransferFunctionWindow": "TF",
        "TimeFrequencyWindow": "TFA",
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._windows: list = []
        self._counters: dict[str, int] = {}

    def next_name(self, window: object) -> str:
        prefix = self.PREFIXES.get(type(window).__name__, "WIN")
        index = self._counters.get(prefix, 0)
        self._counters[prefix] = index + 1
        return f"{prefix} {index:02d}"

    def register(self, window: object) -> str:
        name = self.next_name(window)
        self._windows.append(window)
        self.windows_changed.emit()
        return name

    def unregister(self, window: object) -> None:
        if window in self._windows:
            self._windows.remove(window)
            self.windows_changed.emit()

    @property
    def windows(self) -> list:
        return list(self._windows)

    def others(self, window: object) -> list:
        """Every open window except ``window`` - the import sources."""
        return [w for w in self._windows if w is not window]

    def __len__(self) -> int:
        return len(self._windows)
