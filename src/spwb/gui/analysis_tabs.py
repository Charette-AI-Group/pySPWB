"""The Time Processing window's analysis tabs.

Ports the tabs of ``Time Data Processing (V1.25).vit`` that sit under the
plot: **Scale Signals**, **Stats** and **TV Metrics**. Each is a self
contained widget that reads and writes the window's
:class:`~spwb.processing.model.store.SignalStore`, so the tabs know nothing
about each other and the window stays thin.
"""
from __future__ import annotations

from typing import ClassVar

import numpy as np
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..processing.dsp import conditioning as C
from ..processing.dsp import metrics as M
from ..processing.model.signal import Signal
from ..processing.model.store import SignalStore

__all__ = ["ScaleSignalsTab", "StatsTab", "TVMetricsTab"]


def _copy_table(table: QTableWidget, headers: list[str]) -> str:
    lines = ["\t".join(headers)]
    for row in range(table.rowCount()):
        cells = []
        for col in range(table.columnCount()):
            item = table.item(row, col)
            cells.append(item.text() if item else "")
        lines.append("\t".join(cells))
    return "\n".join(lines)


class _StoreTab(QWidget):
    """Common wiring: rebuild when the store changes, report to the window."""

    def __init__(self, store: SignalStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store

    def refresh(self) -> None:                       # pragma: no cover - base
        raise NotImplementedError

    def _report(self, message: str) -> None:
        window = self.window()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(message)


# --------------------------------------------------------------------------
# Scale Signals
# --------------------------------------------------------------------------
class ScaleSignalsTab(_StoreTab):
    """Per-signal name, unit, calibration factor and DC offset.

    Editing the table stages changes; **Apply** rewrites the signals in the
    store. Staging rather than applying on every keystroke means a typo in
    the middle of entering ``9.81`` does not scale the data by 9.
    """

    COLUMNS: ClassVar[list[str]] = ["Signal", "Unit", "Calib Factor", "DC Offset"]

    def __init__(self, store: SignalStore, parent: QWidget | None = None):
        super().__init__(store, parent)
        # row -> signal id, kept beside the table rather than inside a cell:
        # the Signal cell is user-editable, and anything stored in it is lost
        # the moment that cell is replaced.
        self._row_sids: list[int] = []
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        for col in range(1, len(self.COLUMNS)):
            self.table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeToContents)

        apply_btn = QPushButton("Apply to Signals")
        apply_btn.clicked.connect(self.apply)
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self.refresh)

        self.normalize_box = QComboBox()
        self.normalize_box.addItems(C.NORMALIZATION_OPTIONS)
        self.normalize_box.setCurrentText("To itself")
        normalize_btn = QPushButton("Normalize ALL Signals")
        normalize_btn.clicked.connect(self.normalize)

        row = QHBoxLayout()
        row.addWidget(apply_btn)
        row.addWidget(reset_btn)
        row.addSpacing(24)
        row.addWidget(QLabel("Normalization:"))
        row.addWidget(self.normalize_box)
        row.addWidget(normalize_btn)
        row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Edit a row, then Apply. Factor scales the raw signal; the "
            "offset is added afterwards, in the calibrated unit."))
        layout.addWidget(self.table, 1)
        layout.addLayout(row)

    def refresh(self) -> None:
        signals = list(self.store)
        self._row_sids = [s.sid for s in signals]
        self.table.blockSignals(True)
        self.table.setRowCount(len(signals))
        for r, sig in enumerate(signals):
            self.table.setItem(r, 0, QTableWidgetItem(sig.name))
            self.table.setItem(r, 1, QTableWidgetItem(sig.y_unit))
            self.table.setItem(r, 2, QTableWidgetItem("1"))
            self.table.setItem(r, 3, QTableWidgetItem("0"))
        self.table.blockSignals(False)

    def apply(self) -> None:
        changed = 0
        errors = []
        for r in range(self.table.rowCount()):
            if r >= len(self._row_sids):
                continue
            sid = self._row_sids[r]
            if sid not in self.store:
                continue
            sig = self.store.get(sid)
            name = self.table.item(r, 0).text().strip() or sig.name
            unit = self.table.item(r, 1).text().strip()
            try:
                factor = float(self.table.item(r, 2).text())
                dc = float(self.table.item(r, 3).text())
            except ValueError:
                errors.append(sig.name)
                continue
            if (factor == 1.0 and dc == 0.0 and name == sig.name
                    and unit == sig.y_unit):
                continue
            self.store.update(C.calibrate(sig, factor=factor, dc=dc,
                                          name=name, unit=unit))
            changed += 1

        if errors:
            QMessageBox.warning(
                self, "Scale Signals",
                "These rows have a factor or offset that is not a number, "
                "so they were left alone:\n\n  " + "\n  ".join(errors))
        self._report(f"Applied calibration to {changed} signal(s)"
                     if changed else "Nothing to apply")
        self.refresh()

    def normalize(self) -> None:
        signals = list(self.store)
        if not signals:
            self._report("No signals to normalize")
            return
        option = self.normalize_box.currentText()
        out, max_all = C.normalize(signals, option)
        for scaled in out:          # normalize() keeps each signal's identity
            self.store.update(scaled)
        self._report(f"Normalized {len(out)} signal(s) - {option} "
                     f"(max of all was {max_all:g})")
        self.refresh()


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------
class StatsTab(_StoreTab):
    """``SA Math - Signals Basic Statistics.vi`` as a table."""

    COLUMNS: ClassVar[list[str]] = [
        "Signal", "Min", "Max", "Mean / DC", "RMS", "Peak-Peak", "Crest",
        "Samples", "Duration (ms)",
    ]

    def __init__(self, store: SignalStore, parent: QWidget | None = None):
        super().__init__(store, parent)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        for col in range(1, len(self.COLUMNS)):
            self.table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeToContents)

        copy_btn = QPushButton("Export table to clipboard")
        copy_btn.clicked.connect(self.copy)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(copy_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addLayout(row)

    def refresh(self) -> None:
        signals = list(self.store)
        self.table.setRowCount(len(signals))
        for r, sig in enumerate(signals):
            s = M.signal_statistics(sig)
            unit = f" {s.unit}" if s.unit else ""
            values = [
                s.name,
                f"{s.minimum:.6g}{unit}",
                f"{s.maximum:.6g}{unit}",
                f"{s.mean:.6g}{unit}",
                f"{s.rms:.6g}{unit}",
                f"{s.peak_to_peak:.6g}{unit}",
                f"{s.crest_factor:.4g}",
                str(s.n_samples),
                f"{s.duration_ms:.6g}",
            ]
            for c, text in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(text))

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(
            _copy_table(self.table, self.COLUMNS))
        self._report("Statistics copied to clipboard")


# --------------------------------------------------------------------------
# TV Metrics
# --------------------------------------------------------------------------
class TVMetricsTab(_StoreTab):
    """Sliding-window trends (``SA Cond - Time Varying Metrics.vi``).

    The trend of each visible signal is computed and *added to the store*
    as a new signal, so it plots on the same axes as the data it came from
    and can be exported or sent to another window like anything else.
    """

    def __init__(self, store: SignalStore, parent: QWidget | None = None):
        super().__init__(store, parent)

        self.trend = QComboBox()
        self.trend.addItems(M.TREND_TYPES)

        self.step = QDoubleSpinBox()
        self.step.setRange(0.001, 1e6)
        self.step.setValue(100.0)
        self.step.setDecimals(3)
        self.step.setSuffix(" ms")

        self.length = QDoubleSpinBox()
        self.length.setRange(0.001, 1e6)
        self.length.setValue(1000.0)
        self.length.setDecimals(3)
        self.length.setSuffix(" ms")

        compute = QPushButton("Compute Trends")
        compute.clicked.connect(self.compute)

        self.summary = QTableWidget(0, 4)
        self.summary.setHorizontalHeaderLabels(
            ["Trend", "Points", "Min", "Max"])
        self.summary.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)

        row = QHBoxLayout()
        row.addWidget(QLabel("Type:"))
        row.addWidget(self.trend)
        row.addWidget(QLabel("Step:"))
        row.addWidget(self.step)
        row.addWidget(QLabel("Length:"))
        row.addWidget(self.length)
        row.addWidget(compute)
        row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(QLabel(
            "Each trend is added to the window as a new signal, so it plots "
            "with the data and can be exported or sent to another window."))
        layout.addWidget(self.summary, 1)

    def refresh(self) -> None:
        """Nothing to rebuild: trends are produced on demand."""

    def _source_signals(self) -> list[Signal]:
        window = self.window()
        if hasattr(window, "_visible_signals"):
            visible = [s for s in window._visible_signals()
                       if "TVM_Trend_Type" not in s.attributes]
            if visible:
                return visible
        return [s for s in self.store if "TVM_Trend_Type" not in s.attributes]

    def compute(self) -> None:
        sources = self._source_signals()
        if not sources:
            self._report("No signals to trend")
            return

        trend = self.trend.currentText()
        rows, failures = [], []
        for sig in sources:
            try:
                out = M.time_varying_metric(
                    sig, trend, step_ms=self.step.value(),
                    length_ms=self.length.value(), annotate=True)
            except ValueError as exc:
                failures.append(f"{sig.name}: {exc}")
                continue
            self.store.add(out)
            rows.append((out.name, out.n_samples, float(np.min(out.y)),
                         float(np.max(out.y))))

        self.summary.setRowCount(len(rows))
        for r, (name, points, low, high) in enumerate(rows):
            for c, text in enumerate((name, str(points), f"{low:.6g}",
                                      f"{high:.6g}")):
                self.summary.setItem(r, c, QTableWidgetItem(text))

        if failures:
            self._report("  |  ".join(failures))
        else:
            self._report(f"Added {len(rows)} {trend} trend(s)")
