"""Adaptive Filtering window - port of ``LMS Adaptive Filtering (V1.00).vi``.

Two signals are chosen by role: the **Reference (X)** carries the
contamination, the **Noisy (X + n)** is the signal to clean. The window
shows the cleaned result against the original, the convergence trace, and
the coefficients the filter learned.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..processing.dsp import adaptive as A
from ..processing.model.store import SignalStore
from .bridge import StoreBridge, WindowManager
from .dialogs import ImportFromWindowDialog
from .plotting import SpwbPlot, curve_pen

__all__ = ["LMSWindow"]


class LMSWindow(QMainWindow):
    def __init__(self, manager: WindowManager,
                 store: SignalStore | None = None) -> None:
        super().__init__()
        self.manager = manager
        self.bridge = StoreBridge(store)
        self.window_name = manager.register(self)
        self.setWindowTitle(f"SPWB - Adaptive Filtering  [{self.window_name}]")
        self.resize(1180, 800)

        self._result: A.LMSResult | None = None

        self._build_ui()
        self._build_menus()
        self.bridge.changed.connect(self._refresh_selectors)
        self.manager.windows_changed.connect(self._update_import_action)
        self._refresh_selectors()
        self._update_import_action()

    @property
    def store(self) -> SignalStore:
        return self.bridge.store

    # -- construction --------------------------------------------------------
    def _build_ui(self) -> None:
        palette = self.palette()
        self._bg = palette.color(QPalette.Base)
        self._fg = palette.color(QPalette.WindowText)
        pg.setConfigOptions(antialias=True)

        self.reference_box = QComboBox()
        self.noisy_box = QComboBox()
        for box in (self.reference_box, self.noisy_box):
            box.currentIndexChanged.connect(self._invalidate)

        self.signal_plot = self._plot("Time (sec)", "Amplitude")
        self.signal_legend = self.signal_plot.addLegend(offset=(-10, 10))
        self.convergence_plot = self._plot("Time (sec)", "|x-correlation|")
        self.coefficient_plot = self._plot("Tap", "Weight")

        lower = QSplitter(Qt.Horizontal)
        lower.addWidget(self._titled("Convergence (residual vs reference)",
                                     self.convergence_plot))
        lower.addWidget(self._titled("Learned filter", self.coefficient_plot))
        lower.setSizes([520, 520])

        plots = QSplitter(Qt.Vertical)
        plots.addWidget(self._titled("Signals", self.signal_plot))
        plots.addWidget(lower)
        plots.setStretchFactor(0, 2)
        plots.setSizes([440, 250])

        roles = QHBoxLayout()
        roles.addWidget(QLabel("Reference (X):"))
        roles.addWidget(self.reference_box, 1)
        roles.addWidget(QLabel("Noisy (X + n):"))
        roles.addWidget(self.noisy_box, 1)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(roles)
        layout.addWidget(plots, 1)
        layout.addWidget(self._build_controls())
        self.setCentralWidget(body)
        self.statusBar().showMessage(
            "Import two signals, pick their roles, then Run")

    def _plot(self, x_label: str, y_label: str) -> SpwbPlot:
        return SpwbPlot(x_label, y_label)

    @staticmethod
    def _titled(title: str, widget: QWidget) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(title)
        label.setAlignment(Qt.AlignHCenter)
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return holder

    def _build_controls(self) -> QWidget:
        self.filter_class = QComboBox()
        self.filter_class.addItems(A.LMS_FILTER_CLASSES)
        self.filter_class.setCurrentText("Normalized LMS")

        self.filter_length = QSpinBox()
        self.filter_length.setRange(1, 8192)
        self.filter_length.setValue(64)
        self.filter_length.setToolTip(
            "Number of taps. It must span the delay between the reference "
            "and the contamination, or the filter cannot represent the path.")

        self.step_size = QDoubleSpinBox()
        self.step_size.setRange(0.0001, 1.9999)
        self.step_size.setDecimals(4)
        self.step_size.setValue(0.1)
        self.step_size.setSingleStep(0.05)
        self.step_size.setToolTip(
            "Adaptation rate. The 0 to 2 range applies to the normalised "
            "algorithms; plain LMS needs a far smaller value, scaled by the "
            "reference power.")

        self.keep_removed = QCheckBox("Also keep the removed part")
        self.keep_removed.setToolTip(
            "Adds the contamination the filter identified, so you can check "
            "what was taken out.")

        run = QPushButton("Run")
        run.clicked.connect(self.run)
        self.add_button = QPushButton("Add Result to Window")
        self.add_button.clicked.connect(self.add_result)
        self.add_button.setEnabled(False)

        parameters = QGroupBox("Input Parameters")
        form = QFormLayout(parameters)
        form.addRow("Filter Class:", self.filter_class)
        form.addRow("Filter Length (# coefs):", self.filter_length)
        form.addRow("Step size:", self.step_size)
        form.addRow("", self.keep_removed)

        self.summary = QLabel("-")
        self.summary.setWordWrap(True)
        results = QGroupBox("Result")
        results_layout = QVBoxLayout(results)
        results_layout.addWidget(self.summary, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(run)
        buttons.addWidget(self.add_button)
        results_layout.addLayout(buttons)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(parameters)
        layout.addWidget(results, 1)
        return row

    def _build_menus(self) -> None:
        bar = self.menuBar()
        signals_menu = bar.addMenu("&Signals")
        import_menu = signals_menu.addMenu("Import Signals ...")
        self.import_action = QAction("Another Window", self)
        self.import_action.setShortcut("Ctrl+I")
        self.import_action.triggered.connect(self.import_from_window)
        import_menu.addAction(self.import_action)
        signals_menu.addSeparator()
        act = QAction("Exit", self)
        act.triggered.connect(self.close)
        signals_menu.addAction(act)

        window_menu = bar.addMenu("&Window")
        act = QAction("New Adaptive Filtering Window", self)
        act.setShortcut("Ctrl+N")
        act.triggered.connect(lambda: LMSWindow(self.manager).show())
        window_menu.addAction(act)

    # -- data ----------------------------------------------------------------
    def _refresh_selectors(self) -> None:
        signals = [s for s in self.store if "LMS_Filter_Class" not in
                   s.attributes]
        keep = [box.currentData() for box in
                (self.reference_box, self.noisy_box)]
        for box in (self.reference_box, self.noisy_box):
            box.blockSignals(True)
            box.clear()
            for sig in signals:
                box.addItem(sig.name, sig)
            box.blockSignals(False)

        for box, previous in zip((self.reference_box, self.noisy_box), keep,
                                 strict=True):
            box.blockSignals(True)
            at = box.findData(previous) if previous is not None else -1
            box.setCurrentIndex(max(at, 0))
            box.blockSignals(False)

        # Default the two roles to *different* signals. Signals arrive one at
        # a time, so without this both selectors sit on whichever arrived
        # first, and running would ask the filter to cancel a signal against
        # itself.
        if (len(signals) > 1
                and self.reference_box.currentIndex()
                == self.noisy_box.currentIndex()):
            other = 1 if self.reference_box.currentIndex() == 0 else 0
            self.noisy_box.blockSignals(True)
            self.noisy_box.setCurrentIndex(other)
            self.noisy_box.blockSignals(False)
        self._invalidate()

    def _invalidate(self) -> None:
        self._result = None
        self.add_button.setEnabled(False)

    def run(self) -> None:
        reference = self.reference_box.currentData()
        noisy = self.noisy_box.currentData()
        if reference is None or noisy is None:
            self.statusBar().showMessage("Pick a reference and a noisy signal")
            return
        if reference.sid == noisy.sid:
            QMessageBox.information(
                self, "Adaptive Filtering",
                "The reference and the noisy signal are the same. The filter "
                "would simply cancel everything - pick two different signals.")
            return

        try:
            self._result = A.lms_filter(
                reference, noisy,
                filter_length=self.filter_length.value(),
                step_size=self.step_size.value(),
                filter_class=self.filter_class.currentText())
        except ValueError as exc:
            self._result = None
            self.add_button.setEnabled(False)
            self.summary.setText(str(exc))
            self.statusBar().showMessage("Could not run - see the message")
            self._clear_plots()
            return

        self.add_button.setEnabled(True)
        self._redraw()

    def _clear_plots(self) -> None:
        for plot in (self.signal_plot, self.convergence_plot,
                     self.coefficient_plot):
            plot.clear()
        if self.signal_legend is not None:
            self.signal_legend.clear()

    def _redraw(self) -> None:
        result = self._result
        if result is None:
            return
        noisy = self.noisy_box.currentData()
        self._clear_plots()

        self.signal_plot.plot(noisy.t, noisy.y,
                              pen=curve_pen("#d62728"), name="noisy")
        self.signal_plot.plot(result.filtered.t, result.filtered.y,
                              pen=curve_pen("#1f77b4"),
                              name="filtered")
        self.signal_plot.setLabel("left", f"Amplitude ({noisy.y_unit})"
                                  if noisy.y_unit else "Amplitude")

        self.convergence_plot.plot(result.block_times, result.convergence,
                                   pen=curve_pen("#2ca02c"),
                                   symbol="o", symbolSize=4)
        floor = pg.InfiniteLine(pos=result.noise_floor, angle=0,
                                pen=pg.mkPen("#888888", style=Qt.DotLine))
        self.convergence_plot.addItem(floor)

        taps = np.arange(len(result.coefficients))
        self.coefficient_plot.plot(taps, result.coefficients,
                                   pen=None, symbol="o", symbolSize=4,
                                   symbolBrush="#ff7f0e")

        verdict = "converged" if result.converged else "still adapting"
        gain = result.noise_reduction_db
        warning = ("  The level went UP, so the reference does not carry the "
                   "contamination - check which signal is which."
                   if gain < 0 else "")
        self.summary.setText(
            f"{result.filter_class}, {len(result.coefficients)} taps, step "
            f"{result.step_size:g}\n"
            f"Level change: {gain:+.2f} dB\n"
            f"Convergence: {result.convergence[-1]:.4f} "
            f"(chance level {result.noise_floor:.4f}) - {verdict}.{warning}")
        self.statusBar().showMessage(
            f"{gain:+.2f} dB, {verdict}; press Add Result to keep it")

    def add_result(self) -> None:
        # Take a local reference first: adding to the store fires `changed`,
        # which rebuilds the selectors and clears self._result.
        result = self._result
        if result is None:
            return
        to_add = [result.filtered.copy()]
        if self.keep_removed.isChecked():
            to_add.append(result.removed.copy())
        for signal in to_add:
            self.store.add(signal)
        self.statusBar().showMessage(
            f"Added {len(to_add)} signal(s) to this window")

    # -- actions -------------------------------------------------------------
    def _update_import_action(self) -> None:
        self.import_action.setEnabled(
            bool([w for w in self.manager.others(self) if hasattr(w, "store")]))

    def import_from_window(self) -> None:
        sources = [w for w in self.manager.others(self) if hasattr(w, "store")]
        if not sources:
            QMessageBox.information(self, "Import Signals",
                                    "No other window is open.")
            return
        dialog = ImportFromWindowDialog(sources, self)
        if dialog.exec() != ImportFromWindowDialog.Accepted:
            return
        for sig in dialog.selected_signals():
            if sig.sid not in self.store:
                self.store.add(sig)

    def closeEvent(self, event) -> None:
        self.manager.unregister(self)
        self.bridge.close()
        super().closeEvent(event)
