"""Dialogs for the SPWB windows."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..processing.model.signal import Signal

__all__ = ["ChannelSelectDialog", "CreateSignalDialog", "ImportFromWindowDialog"]


class ImportFromWindowDialog(QDialog):
    """``Signals > Import Signals ... > Another Window``.

    The feature that in LabVIEW needed VI-server references and queues: here
    every window is an object in the same process, so importing is a copy.
    """

    def __init__(self, sources: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Signals from Another Window")
        self.resize(460, 380)
        self._sources = sources

        self.window_box = QComboBox()
        for w in sources:
            self.window_box.addItem(f"{w.window_name}  ({len(w.store)} signals)", w)
        self.window_box.currentIndexChanged.connect(self._refresh)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)

        self.copy_box = QCheckBox("Import as independent copies")
        self.copy_box.setChecked(True)
        self.copy_box.setToolTip(
            "Checked: the imported signals are snapshots, independent of the "
            "source window (LabVIEW behaviour).\n"
            "Unchecked: import the same Signal objects, so both windows show "
            "the identical data."
        )

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Source window:"))
        layout.addWidget(self.window_box)
        layout.addWidget(QLabel("Signals to import:"))
        layout.addWidget(self.list, 1)
        layout.addWidget(self.copy_box)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self) -> None:
        self.list.clear()
        window = self.window_box.currentData()
        if window is None:
            return
        for sig in window.store:
            item = QListWidgetItem(f"{sig.name}   [{sig.n_samples} pts, "
                                   f"{sig.fs:g} Hz, {sig.y_unit or '-'}]")
            item.setData(Qt.UserRole, sig)
            self.list.addItem(item)
        self.list.selectAll()

    def selected_signals(self) -> list[Signal]:
        out = []
        for item in self.list.selectedItems():
            sig: Signal = item.data(Qt.UserRole)
            out.append(sig.copy() if self.copy_box.isChecked() else sig)
        return out


class ChannelSelectDialog(QDialog):
    """Channel picker for TDMS import (``GUI - TDMS (V2.00).vi``)."""

    def __init__(self, channels: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Channels to Import")
        self.resize(460, 400)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        for info in channels:
            label = f"{info.path}   [{info.n_samples} pts"
            label += f", {1 / info.dt:g} Hz]" if info.dt else ", no timing]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, info)
            if not info.is_waveform:
                item.setToolTip("No wf_increment property; needs a sample rate.")
            self.list.addItem(item)
        self.list.selectAll()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Channels found in the file:"))
        layout.addWidget(self.list, 1)
        layout.addWidget(buttons)

    def selected_paths(self) -> list[str]:
        return [i.data(Qt.UserRole).path for i in self.list.selectedItems()]

    def needs_dt(self) -> bool:
        return any(not i.data(Qt.UserRole).is_waveform
                   for i in self.list.selectedItems())


class CreateSignalDialog(QDialog):
    """``Signals > Create ...`` - periodic, sweep and random generators."""

    KINDS = ("Sine", "Square", "Triangle", "Sine Sweep", "Random (Gaussian)",
             "Random (Uniform)")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Signal")

        self.kind = QComboBox()
        self.kind.addItems(self.KINDS)
        self.kind.currentTextChanged.connect(self._update_enabled)

        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.addItems(["Generated", "Signal", "Test"])

        self.fs = QDoubleSpinBox()
        self.fs.setRange(1.0, 10e6)
        self.fs.setValue(51200.0)
        self.fs.setSuffix(" Hz")
        self.fs.setDecimals(2)

        self.duration = QDoubleSpinBox()
        self.duration.setRange(1e-3, 3600.0)
        self.duration.setValue(1.0)
        self.duration.setSuffix(" s")
        self.duration.setDecimals(4)

        self.amplitude = QDoubleSpinBox()
        self.amplitude.setRange(-1e9, 1e9)
        self.amplitude.setValue(1.0)

        self.freq = QDoubleSpinBox()
        self.freq.setRange(0.0, 10e6)
        self.freq.setValue(1000.0)
        self.freq.setSuffix(" Hz")

        self.freq_end = QDoubleSpinBox()
        self.freq_end.setRange(0.0, 10e6)
        self.freq_end.setValue(10000.0)
        self.freq_end.setSuffix(" Hz")

        self.unit = QComboBox()
        self.unit.setEditable(True)
        self.unit.addItems(["", "V", "Pa", "m/s^2", "m/s", "m", "N"])

        form = QFormLayout()
        form.addRow("Type:", self.kind)
        form.addRow("Name:", self.name)
        form.addRow("Sample rate:", self.fs)
        form.addRow("Duration:", self.duration)
        form.addRow("Amplitude:", self.amplitude)
        form.addRow("Frequency:", self.freq)
        form.addRow("End frequency:", self.freq_end)
        form.addRow("Unit:", self.unit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._update_enabled(self.kind.currentText())

    def _update_enabled(self, kind: str) -> None:
        periodic = kind in ("Sine", "Square", "Triangle")
        sweep = kind == "Sine Sweep"
        self.freq.setEnabled(periodic or sweep)
        self.freq_end.setEnabled(sweep)

    def build(self) -> Signal:
        fs = self.fs.value()
        dt = 1.0 / fs
        n = max(2, int(round(self.duration.value() * fs)))
        t = np.arange(n) * dt
        a = self.amplitude.value()
        f0 = self.freq.value()
        kind = self.kind.currentText()

        if kind == "Sine":
            y = a * np.sin(2 * np.pi * f0 * t)
        elif kind == "Square":
            y = a * np.sign(np.sin(2 * np.pi * f0 * t))
        elif kind == "Triangle":
            y = a * (2.0 / np.pi) * np.arcsin(np.sin(2 * np.pi * f0 * t))
        elif kind == "Sine Sweep":
            f1 = max(self.freq_end.value(), 1e-9)
            f0 = max(f0, 1e-9)
            duration = n * dt
            # logarithmic sweep, as SPWB's Sine Sweep Signal.vi generates
            k = math.log(f1 / f0)
            phase = 2 * np.pi * f0 * duration / k * (np.exp(t * k / duration) - 1)
            y = a * np.sin(phase)
        elif kind == "Random (Gaussian)":
            y = a * np.random.default_rng().standard_normal(n)
        else:
            y = a * np.random.default_rng().uniform(-1.0, 1.0, n)

        return Signal(
            name=self.name.currentText().strip() or "Generated",
            y=y, dt=dt, y_unit=self.unit.currentText().strip(),
            attributes={"Data Source": f"Generated ({kind})",
                        "Channel Name": self.name.currentText().strip()},
        )
