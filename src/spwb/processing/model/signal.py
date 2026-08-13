"""Signal model - the Python equivalent of SPWB's wForm.

A LabVIEW waveform is {t0, dt, Y, attributes}. SPWB leans heavily on the
attribute dictionary to carry processing provenance between its GUIs
(FFT_Window_Type, FFT_Coherent_Gain, X_UnitDescription, ...), so attributes
are first-class here.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

import numpy as np

_id_counter = itertools.count(1)


@dataclass
class Signal:
    """One channel of sampled data plus its metadata."""

    name: str
    y: np.ndarray
    dt: float
    t0: float = 0.0
    y_unit: str = ""
    x_unit: str = "s"
    attributes: dict[str, Any] = field(default_factory=dict)
    #: unique id used by the SignalStore; never reused within a session
    sid: int = field(default_factory=lambda: next(_id_counter))

    def __post_init__(self) -> None:
        self.y = np.asarray(self.y, dtype=float)
        if self.y.ndim != 1:
            raise ValueError("Signal.y must be 1-D (one Signal per channel)")
        if self.dt <= 0:
            raise ValueError("Signal.dt must be positive")

    # -- LabVIEW-waveform-style accessors ------------------------------------
    @property
    def fs(self) -> float:
        """Sampling rate in Hz."""
        return 1.0 / self.dt

    @property
    def n_samples(self) -> int:
        return len(self.y)

    @property
    def duration(self) -> float:
        return self.n_samples * self.dt

    @property
    def t(self) -> np.ndarray:
        """Time (or abscissa) vector."""
        return self.t0 + np.arange(self.n_samples) * self.dt

    def _replace(self, changes: dict[str, Any], keep_sid: bool) -> Signal:
        merged: dict[str, Any] = dict(
            name=self.name, y=self.y.copy(), dt=self.dt, t0=self.t0,
            y_unit=self.y_unit, x_unit=self.x_unit,
            attributes=dict(self.attributes),
        )
        if keep_sid:
            merged["sid"] = self.sid
        attrs = changes.pop("attributes", None)
        merged.update(changes)
        if attrs is not None:
            merged["attributes"] = {**dict(self.attributes), **attrs}
        return Signal(**merged)

    def with_(self, **changes: Any) -> Signal:
        """Return a revision of this signal: same identity, fields replaced.

        The ``sid`` is preserved so the result can be handed to
        :meth:`SignalStore.update`. Use :meth:`copy` for an independent
        signal. ``attributes`` is shallow-merged; ``y`` is copied.
        """
        return self._replace(changes, keep_sid=True)

    def copy(self, **changes: Any) -> Signal:
        """Return an independent signal with a fresh identity.

        This is what importing into another window or duplicating a window
        produces: the two signals then evolve separately, matching the value
        semantics of LabVIEW wires.
        """
        return self._replace(changes, keep_sid=False)

    def __repr__(self) -> str:  # keep the repr short for GUI lists
        return (f"Signal({self.name!r}, n={self.n_samples}, fs={self.fs:g} Hz, "
                f"unit={self.y_unit!r})")
