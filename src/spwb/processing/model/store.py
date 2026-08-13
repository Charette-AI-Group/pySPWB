"""SignalStore - the shared registry behind SPWB's multi-window signal sharing.

In the LabVIEW app every GUI instance kept its own signals and shared them
through queues and VI-server messages. Here all tool windows live in one
process, so sharing is a plain observable registry: publish a Signal, any
window (or script) can look it up or subscribe to changes.

The store is deliberately Qt-free so the core library stays importable in
scripts and notebooks; the GUI layer bridges these callbacks to Qt signals.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Literal

from .signal import Signal

Event = Literal["added", "updated", "removed"]
Subscriber = Callable[[Event, Signal], None]


class SignalStore:
    def __init__(self) -> None:
        self._signals: dict[int, Signal] = {}
        self._subscribers: list[Subscriber] = []

    # -- registry ------------------------------------------------------------
    def add(self, signal: Signal) -> Signal:
        if signal.sid in self._signals:
            raise KeyError(f"signal id {signal.sid} already in store")
        self._signals[signal.sid] = signal
        self._notify("added", signal)
        return signal

    def update(self, signal: Signal) -> Signal:
        if signal.sid not in self._signals:
            raise KeyError(f"signal id {signal.sid} not in store")
        self._signals[signal.sid] = signal
        self._notify("updated", signal)
        return signal

    def remove(self, sid: int) -> Signal:
        signal = self._signals.pop(sid)
        self._notify("removed", signal)
        return signal

    def get(self, sid: int) -> Signal:
        return self._signals[sid]

    def find(self, name: str) -> list[Signal]:
        return [s for s in self._signals.values() if s.name == name]

    def __iter__(self) -> Iterator[Signal]:
        return iter(list(self._signals.values()))

    def __len__(self) -> int:
        return len(self._signals)

    def __contains__(self, sid: int) -> bool:
        return sid in self._signals

    # -- pub/sub -------------------------------------------------------------
    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        """Register a callback; returns an unsubscribe function."""
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def _notify(self, event: Event, signal: Signal) -> None:
        for cb in list(self._subscribers):
            cb(event, signal)
