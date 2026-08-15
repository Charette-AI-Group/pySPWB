"""Transfer Function window - port of ``TF Analysis (V1.25).vit``.

Signals are tagged as *references* (inputs) or *responses* (outputs), and
every reference x response combination gets a frequency response and a
coherence, as ``TFSA - TF and Coherence V2.vi`` computed them.

The original front panel put the two lists side by side on a "Signal
Selection" tab; here one list carries a Role column you click to toggle,
which keeps the assignment visible next to the data it applies to.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..processing.dsp import transfer as T
from ..processing.dsp.windows import WINDOW_NAMES
from ..processing.model.signal import Signal
from ..processing.model.store import SignalStore
from .bridge import StoreBridge, WindowManager
from .dialogs import ImportFromWindowDialog
from .fft_analysis import _WINDOW_LABELS
from .plotting import SpwbPlot, curve_pen

__all__ = ["TransferFunctionWindow"]

ROLES = ("Reference", "Response", "(unused)")


class TransferFunctionWindow(QMainWindow):
    def __init__(self, manager: WindowManager,
                 store: SignalStore | None = None) -> None:
        super().__init__()
        self.manager = manager
        self.bridge = StoreBridge(store)
        self.window_name = manager.register(self)
        self.setWindowTitle(f"SPWB - Transfer Functions  [{self.window_name}]")
        self.resize(1180, 760)

        self._roles: dict[int, str] = {}          # sid -> role
        self._results: list[tuple[Signal, Signal]] = []

        self._build_ui()
        self._build_menus()

        self.bridge.changed.connect(self._on_store_changed)
        self.manager.windows_changed.connect(self._update_import_action)
        self._on_store_changed()
        self._update_import_action()

    @property
    def store(self) -> SignalStore:
        return self.bridge.store

    # -- construction --------------------------------------------------------
    def _build_ui(self) -> None:
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Signal", "Role", "Samples", "Unit"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, self.tree.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.tree.itemDoubleClicked.connect(
            lambda item, _col: self._cycle_role(item))

        ref_btn = QPushButton("Mark as Reference")
        ref_btn.clicked.connect(lambda: self._set_role("Reference"))
        resp_btn = QPushButton("Mark as Response")
        resp_btn.clicked.connect(lambda: self._set_role("Response"))
        role_row = QHBoxLayout()
        role_row.addWidget(ref_btn)
        role_row.addWidget(resp_btn)

        import_btn = QPushButton("Import Signals ...")
        import_btn.clicked.connect(self.import_from_window)
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete_selected)
        button_row = QHBoxLayout()
        button_row.addWidget(import_btn)
        button_row.addWidget(delete_btn)

        self.result_list = QTreeWidget()
        self.result_list.setHeaderLabels(["Transfer Function", "Averages"])
        self.result_list.setRootIsDecorated(False)
        self.result_list.setAlternatingRowColors(True)
        self.result_list.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.result_list.itemChanged.connect(
            lambda *_: self._replot())

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.addWidget(QLabel("Signals (double-click to cycle role)"))
        left_layout.addWidget(self.tree, 1)
        left_layout.addLayout(role_row)
        left_layout.addLayout(button_row)
        left_layout.addWidget(QLabel("Results"))
        left_layout.addWidget(self.result_list, 1)

        self.plot = SpwbPlot("Frequency (Hz)", "Magnitude")
        self.legend = self.plot.addLegend(offset=(-10, 10))

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.plot)
        right.addWidget(self._build_tabs())
        right.setStretchFactor(0, 1)
        right.setSizes([500, 230])

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([390, 790])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Mark at least one reference and "
                                     "one response")

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()

        self.freq_resolution = QDoubleSpinBox()
        self.freq_resolution.setRange(1e-4, 1e5)
        self.freq_resolution.setValue(1.0)
        self.freq_resolution.setDecimals(4)
        self.freq_resolution.setSuffix(" Hz")

        self.overlap = QDoubleSpinBox()
        self.overlap.setRange(0.0, 95.0)
        self.overlap.setValue(50.0)
        self.overlap.setDecimals(1)
        self.overlap.setSuffix(" %")

        self.window_box = QComboBox()
        for name in WINDOW_NAMES:
            self.window_box.addItem(_WINDOW_LABELS.get(name, name), name)
        self.window_box.setCurrentIndex(WINDOW_NAMES.index("bh_7term"))

        self.estimator = QComboBox()
        self.estimator.addItems(T.TF_ESTIMATORS)
        self.estimator.setToolTip(
            "H1: noise assumed on the response (SPWB's estimator)\n"
            "H2: noise assumed on the reference\n"
            "H3: geometric mean of the two")

        self.display_type = QComboBox()
        self.display_type.addItems(T.TF_DISPLAY_TYPES)

        params = QGroupBox("Spectral Function Parameters")
        params_form = QFormLayout(params)
        params_form.addRow("Frequency resolution:", self.freq_resolution)
        params_form.addRow("Overlap:", self.overlap)
        params_form.addRow("Window:", self.window_box)

        display = QGroupBox("Transfer Function")
        display_form = QFormLayout(display)
        display_form.addRow("Estimator:", self.estimator)
        display_form.addRow("Transfer Function Type:", self.display_type)

        tf_tab = QWidget()
        tf_layout = QHBoxLayout(tf_tab)
        tf_layout.addWidget(params)
        tf_layout.addWidget(display, 1)
        tabs.addTab(tf_tab, "Transfer Functions")

        for widget in (self.freq_resolution, self.overlap):
            widget.valueChanged.connect(self.recompute)
        for widget in (self.window_box, self.estimator):
            widget.currentIndexChanged.connect(self.recompute)
        self.display_type.currentIndexChanged.connect(self._replot)

        # --- Energy Band -------------------------------------------------
        self.band_start = QDoubleSpinBox()
        self.band_start.setRange(0.0, 1e6)
        self.band_end = QDoubleSpinBox()
        self.band_end.setRange(0.0, 1e6)
        self.band_end.setValue(1000.0)
        for widget in (self.band_start, self.band_end):
            widget.setSuffix(" Hz")
            widget.valueChanged.connect(self._update_band_table)

        self.band_table = QTableWidget(0, 3)
        self.band_table.setHorizontalHeaderLabels(
            ["Transfer Function", "Mean |H|", "Mean Coherence"])
        self.band_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        copy_btn = QPushButton("Export table to clipboard")
        copy_btn.clicked.connect(self.copy_band_table)

        band_tab = QWidget()
        band_layout = QVBoxLayout(band_tab)
        row = QHBoxLayout()
        row.addWidget(QLabel("Start Frequency:"))
        row.addWidget(self.band_start)
        row.addWidget(QLabel("End Frequency:"))
        row.addWidget(self.band_end)
        row.addStretch(1)
        row.addWidget(copy_btn)
        band_layout.addLayout(row)
        band_layout.addWidget(self.band_table, 1)
        tabs.addTab(band_tab, "Energy Band")

        # --- Graph Options -----------------------------------------------
        self.log_x = QComboBox()
        self.log_x.addItems(["Linear", "Logarithmic"])
        self.log_y = QComboBox()
        self.log_y.addItems(["Linear", "Logarithmic"])
        self.log_x.currentIndexChanged.connect(self._replot)
        self.log_y.currentIndexChanged.connect(self._apply_graph_options)

        graph_tab = QWidget()
        graph_form = QFormLayout(graph_tab)
        graph_form.addRow("Frequency axis:", self.log_x)
        graph_form.addRow("Amplitude axis:", self.log_y)
        tabs.addTab(graph_tab, "Graph Options")
        return tabs

    def _build_menus(self) -> None:
        bar = self.menuBar()
        signals_menu = bar.addMenu("&Signals")
        import_menu = signals_menu.addMenu("Import Signals ...")
        self.import_action = QAction("Another Window", self)
        self.import_action.setShortcut("Ctrl+I")
        self.import_action.triggered.connect(self.import_from_window)
        import_menu.addAction(self.import_action)
        signals_menu.addSeparator()
        act = QAction("Export results to clipboard", self)
        act.triggered.connect(self.copy_results)
        signals_menu.addAction(act)
        act = QAction("Exit", self)
        act.triggered.connect(self.close)
        signals_menu.addAction(act)

        window_menu = bar.addMenu("&Window")
        act = QAction("New TF Window", self)
        act.setShortcut("Ctrl+N")
        act.triggered.connect(lambda: TransferFunctionWindow(self.manager).show())
        window_menu.addAction(act)

    # -- roles ---------------------------------------------------------------
    def _set_role(self, role: str) -> None:
        for item in self.tree.selectedItems():
            self._roles[item.data(0, Qt.UserRole).sid] = role
        self.recompute()

    def _cycle_role(self, item: QTreeWidgetItem) -> None:
        sid = item.data(0, Qt.UserRole).sid
        current = self._roles.get(sid, "(unused)")
        self._roles[sid] = ROLES[(ROLES.index(current) + 1) % len(ROLES)]
        self.recompute()

    def signals_with_role(self, role: str) -> list[Signal]:
        return [s for s in self.store if self._roles.get(s.sid) == role]

    def _on_store_changed(self) -> None:
        """New signals default to Response; the first one becomes Reference."""
        for sig in self.store:
            if sig.sid not in self._roles:
                self._roles[sig.sid] = (
                    "Reference" if not self.signals_with_role("Reference")
                    else "Response")
        self._roles = {sid: role for sid, role in self._roles.items()
                       if sid in self.store}
        self.recompute()

    # -- computation ---------------------------------------------------------
    def recompute(self) -> None:
        references = self.signals_with_role("Reference")
        responses = self.signals_with_role("Response")
        self._results = []
        message = ""
        if references and responses:
            try:
                self._results = T.transfer_functions(
                    references, responses,
                    freq_resolution=self.freq_resolution.value(),
                    overlap=self.overlap.value() / 100.0,
                    window=self.window_box.currentData(),
                    estimator=self.estimator.currentText())
                message = (f"{len(self._results)} transfer function(s) "
                           f"in {self.window_name}")
            except ValueError as exc:
                message = str(exc)
        else:
            message = "Mark at least one reference and one response"

        self._refresh_lists()
        self._replot()
        self._update_band_table()
        self.statusBar().showMessage(message)

    def _refresh_lists(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        for sig in self.store:
            item = QTreeWidgetItem([sig.name, self._roles.get(sig.sid, "(unused)"),
                                    str(sig.n_samples), sig.y_unit or "-"])
            item.setData(0, Qt.UserRole, sig)
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)

        checked = {}
        for i in range(self.result_list.topLevelItemCount()):
            it = self.result_list.topLevelItem(i)
            checked[it.text(0)] = it.checkState(0) == Qt.Checked
        self.result_list.blockSignals(True)
        self.result_list.clear()
        for tf, _ in self._results:
            item = QTreeWidgetItem(
                [tf.name, str(tf.attributes.get("FFT_Nb_Averages", "-"))])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if checked.get(tf.name, True)
                               else Qt.Unchecked)
            self.result_list.addTopLevelItem(item)
        self.result_list.blockSignals(False)

    def _visible_results(self) -> list[tuple[Signal, Signal]]:
        visible = set()
        for i in range(self.result_list.topLevelItemCount()):
            item = self.result_list.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                visible.add(item.text(0))
        return [(tf, coh) for tf, coh in self._results if tf.name in visible]

    def _replot(self) -> None:
        self.plot.clear()
        if self.legend is not None:
            self.legend.clear()
        display = self.display_type.currentText()
        log_x = self.log_x.currentIndex() == 1
        units = set()
        for i, (tf, coh) in enumerate(self._visible_results()):
            shown = T.format_transfer_function(tf, display, coh)
            freqs, values = shown.t, shown.y
            if log_x:
                freqs, values = freqs[1:], values[1:]   # log10(0 Hz) = -inf
            self.plot.plot(freqs, values, pen=curve_pen(i), name=shown.name)
            units.add(shown.y_unit)
        label = units.pop() if len(units) == 1 else ""
        self.plot.setLabel("left", f"{display} {f'({label})' if label else ''}")
        if display == "Coherence":
            self.plot.setYRange(0.0, 1.05)
        else:
            self.plot.enableAutoRange(axis="y")
        self._apply_graph_options()

    def _apply_graph_options(self) -> None:
        coherence = self.display_type.currentText() == "Coherence"
        self.plot.setLogMode(x=self.log_x.currentIndex() == 1,
                             y=self.log_y.currentIndex() == 1 and not coherence)

    # -- band table ----------------------------------------------------------
    def _update_band_table(self) -> None:
        lo, hi = self.band_start.value(), self.band_end.value()
        if hi < lo:
            lo, hi = hi, lo
        rows = []
        for tf, coh in self._results:
            mask = (tf.t >= lo) & (tf.t <= hi)
            if not mask.any():
                continue
            rows.append((tf.name, float(np.mean(tf.y[mask])),
                         float(np.mean(coh.y[mask])), tf.y_unit))
        self.band_table.setRowCount(len(rows))
        for r, (name, mag, gamma, unit) in enumerate(rows):
            self.band_table.setItem(r, 0, QTableWidgetItem(name))
            self.band_table.setItem(r, 1, QTableWidgetItem(
                f"{mag:.6g} {unit}".strip()))
            self.band_table.setItem(r, 2, QTableWidgetItem(f"{gamma:.4f}"))

    def copy_band_table(self) -> None:
        lines = ["Transfer Function\tMean |H|\tMean Coherence"]
        for r in range(self.band_table.rowCount()):
            lines.append("\t".join(
                self.band_table.item(r, c).text() if self.band_table.item(r, c)
                else "" for c in range(3)))
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage("Band table copied to clipboard")

    def copy_results(self) -> None:
        visible = self._visible_results()
        if not visible:
            QMessageBox.information(self, "Export", "No results to export.")
            return
        display = self.display_type.currentText()
        shown = [T.format_transfer_function(tf, display, coh)
                 for tf, coh in visible]
        header = ["Frequency (Hz)"] + [f"{s.name} [{display}]" for s in shown]
        lines = ["\t".join(header)]
        for i, f in enumerate(shown[0].t):
            lines.append("\t".join([f"{f:g}"] + [f"{s.y[i]:g}" for s in shown]))
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage(f"{len(shown)} result(s) copied")

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

    def delete_selected(self) -> None:
        for item in self.tree.selectedItems():
            sig: Signal = item.data(0, Qt.UserRole)
            if sig.sid in self.store:
                self.store.remove(sig.sid)

    def closeEvent(self, event) -> None:
        self.manager.unregister(self)
        self.bridge.close()
        super().closeEvent(event)
