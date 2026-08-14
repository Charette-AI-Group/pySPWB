"""FFT Analysis window - port of ``FFT Analysis (V1.25).vit``.

Takes time signals (imported from a Time Processing window, or any other
window) and shows their spectra. The controls mirror the original front
panel: frequency resolution, overlap, window, spectral function type,
spectrum display options and acoustic weighting, plus the Energy Band tab.

Spectra are recomputed from the source time signals whenever a parameter
changes, so the window always shows a result consistent with its settings -
the LabVIEW original had to drive this through its state machine.
"""
from __future__ import annotations

import pyqtgraph as pg
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

from ..processing.dsp import spectral as S
from ..processing.dsp.windows import WINDOW_NAMES
from ..processing.model.signal import Signal
from ..processing.model.store import SignalStore
from .bridge import StoreBridge, WindowManager
from .dialogs import ImportFromWindowDialog
from .plotting import SpwbPlot

__all__ = ["FFTWindow"]

_PEN_COLOURS = ("#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd",
                "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f")

# window names as the SPWB menu spelled them
_WINDOW_LABELS = {
    "rectangular": "Rectangle", "hanning": "Hanning", "hamming": "Hamming",
    "blackman_harris": "Blackman-Harris", "exact_blackman": "Exact Blackman",
    "blackman": "Blackman", "flat_top": "Flat Top",
    "bh_4term": "4 Term B-Harris", "bh_7term": "7 Term B-Harris",
    "low_sidelobe": "Low Sidelobe", "blackman_nuttall": "Blackman Nuttall",
    "triangle": "Triangle", "bartlett_hanning": "Bartlett-Hanning",
    "bohman": "Bohman", "parzen": "Parzen", "welch": "Welch",
    "kaiser": "Kaiser", "dolph_chebyshev": "Dolph-Chebyshev",
    "gaussian": "Gaussian",
}


class FFTWindow(QMainWindow):
    def __init__(self, manager: WindowManager,
                 store: SignalStore | None = None) -> None:
        super().__init__()
        self.manager = manager
        self.bridge = StoreBridge(store)          # holds the *time* signals
        self.window_name = manager.register(self)
        self.setWindowTitle(f"SPWB - FFT Analysis  [{self.window_name}]")
        self.resize(1150, 720)

        self._spectra: dict[int, Signal] = {}     # sid -> displayed spectrum
        self._updating = False

        self._build_ui()
        self._build_menus()

        self.bridge.changed.connect(self.recompute)
        self.manager.windows_changed.connect(self._update_import_action)
        self.recompute()
        self._update_import_action()

    @property
    def store(self) -> SignalStore:
        return self.bridge.store

    # -- construction --------------------------------------------------------
    def _build_ui(self) -> None:
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Signal", "Averages", "df (Hz)", "Unit"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemChanged.connect(self._on_item_changed)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, self.tree.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        import_btn = QPushButton("Import Signals ...")
        import_btn.clicked.connect(self.import_from_window)
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete_selected)
        row = QHBoxLayout()
        row.addWidget(import_btn)
        row.addWidget(delete_btn)
        row.addStretch(1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.addWidget(QLabel("Signals in this window"))
        left_layout.addWidget(self.tree, 1)
        left_layout.addLayout(row)

        pg.setConfigOptions(antialias=True)
        # plain label, not units="Hz": pyqtgraph's SI auto-prefixing rescales
        # to kHz and makes the log-frequency ticks unreadable
        self.plot = SpwbPlot("Frequency (Hz)", "Amplitude")
        self.legend = self.plot.addLegend(offset=(-10, 10))

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.plot)
        right.addWidget(self._build_tabs())
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 0)
        right.setSizes([480, 220])

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 790])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready")

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()

        # --- Spectral Analysis ------------------------------------------
        self.freq_resolution = QDoubleSpinBox()
        self.freq_resolution.setRange(1e-4, 1e5)
        self.freq_resolution.setValue(1.0)
        self.freq_resolution.setDecimals(4)
        self.freq_resolution.setSuffix(" Hz")

        self.overlap = QDoubleSpinBox()
        self.overlap.setRange(0.0, 95.0)
        self.overlap.setValue(0.0)
        self.overlap.setDecimals(1)
        self.overlap.setSuffix(" %")

        self.window_box = QComboBox()
        for name in WINDOW_NAMES:
            self.window_box.addItem(_WINDOW_LABELS.get(name, name), name)
        self.window_box.setCurrentIndex(WINDOW_NAMES.index("hanning"))

        self.window_parameter = QDoubleSpinBox()
        self.window_parameter.setRange(-1e3, 1e3)
        self.window_parameter.setDecimals(3)
        self.window_parameter.setToolTip(
            "Kaiser beta, Gaussian std (fraction of length), or "
            "Dolph-Chebyshev sidelobe ratio in dB")

        self.function_type = QComboBox()
        self.function_type.addItems(S.SPECTRAL_FUNCTION_TYPES)
        self.display_option = QComboBox()
        self.display_option.addItems(S.SPECTRUM_DISPLAY_OPTIONS)
        self.weighting = QComboBox()
        self.weighting.addItems(S.ACOUSTIC_WEIGHTINGS)

        params = QGroupBox("Spectral Function Parameters")
        params_form = QFormLayout(params)
        params_form.addRow("Frequency resolution:", self.freq_resolution)
        params_form.addRow("Overlap:", self.overlap)
        params_form.addRow("Window:", self.window_box)
        params_form.addRow("Window parameter:", self.window_parameter)

        display = QGroupBox("Display")
        display_form = QFormLayout(display)
        display_form.addRow("Spectral Function Type:", self.function_type)
        display_form.addRow("Spectrum Display Options:", self.display_option)
        display_form.addRow("Acoustic Weighting:", self.weighting)

        spectral_tab = QWidget()
        spectral_layout = QHBoxLayout(spectral_tab)
        spectral_layout.addWidget(params)
        spectral_layout.addWidget(display, 1)
        tabs.addTab(spectral_tab, "Spectral Analysis")

        for widget in (self.freq_resolution, self.overlap,
                       self.window_parameter):
            widget.valueChanged.connect(self.recompute)
        # sync the parameter *before* recomputing, so a window change never
        # computes with the previous window's parameter (e.g. Gaussian std 0)
        self.window_box.currentIndexChanged.connect(self._sync_window_parameter)
        for widget in (self.window_box, self.function_type,
                       self.display_option, self.weighting):
            widget.currentIndexChanged.connect(self.recompute)
        self._sync_window_parameter()

        # --- Energy Band -------------------------------------------------
        self.band_start = QDoubleSpinBox()
        self.band_start.setRange(0.0, 1e6)
        self.band_start.setValue(0.0)
        self.band_start.setSuffix(" Hz")
        self.band_end = QDoubleSpinBox()
        self.band_end.setRange(0.0, 1e6)
        self.band_end.setValue(1000.0)
        self.band_end.setSuffix(" Hz")
        for widget in (self.band_start, self.band_end):
            widget.valueChanged.connect(self._update_energy_band)

        self.band_table = QTableWidget(0, 3)
        self.band_table.setHorizontalHeaderLabels(
            ["Signal", "Band RMS", "Band Power"])
        self.band_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        copy_btn = QPushButton("Export table to clipboard")
        copy_btn.clicked.connect(self.copy_band_table)

        band_tab = QWidget()
        band_layout = QVBoxLayout(band_tab)
        band_form = QHBoxLayout()
        band_form.addWidget(QLabel("Start Frequency:"))
        band_form.addWidget(self.band_start)
        band_form.addWidget(QLabel("End Frequency:"))
        band_form.addWidget(self.band_end)
        band_form.addStretch(1)
        band_form.addWidget(copy_btn)
        band_layout.addLayout(band_form)
        band_layout.addWidget(self.band_table, 1)
        tabs.addTab(band_tab, "Energy Band")

        # --- Graph Options -----------------------------------------------
        self.log_x = QComboBox()
        self.log_x.addItems(["Linear", "Logarithmic"])
        self.log_y = QComboBox()
        self.log_y.addItems(["Linear", "Logarithmic"])
        # log-x needs a full replot (the DC bin is dropped), not just a mode flip
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
        act = QAction("Export spectra to clipboard", self)
        act.triggered.connect(self.copy_spectra)
        signals_menu.addAction(act)
        act = QAction("Exit", self)
        act.triggered.connect(self.close)
        signals_menu.addAction(act)

        window_menu = bar.addMenu("&Window")
        act = QAction("New FFT Window", self)
        act.setShortcut("Ctrl+N")
        act.triggered.connect(self.new_window)
        window_menu.addAction(act)
        act = QAction("Duplicate Current Window", self)
        act.triggered.connect(self.duplicate_window)
        window_menu.addAction(act)

    # -- parameters ----------------------------------------------------------
    @property
    def window_name_selected(self) -> str:
        return self.window_box.currentData()

    def _sync_window_parameter(self) -> None:
        """Only Kaiser / Chebyshev / Gaussian take a parameter."""
        defaults = {"kaiser": 0.0, "dolph_chebyshev": 60.0, "gaussian": 0.2}
        name = self.window_name_selected
        enabled = name in defaults
        self.window_parameter.setEnabled(enabled)
        if enabled:
            self._updating = True
            self.window_parameter.setValue(defaults[name])
            self._updating = False

    # -- computation ---------------------------------------------------------
    def recompute(self) -> None:
        """Recompute every spectrum from its source time signal."""
        if self._updating:
            return
        import math

        name = self.window_name_selected
        parameter = (self.window_parameter.value()
                     if self.window_parameter.isEnabled() else math.nan)
        df = self.freq_resolution.value()
        overlap = self.overlap.value() / 100.0

        self._spectra.clear()
        failures = []
        for sig in self.store:
            try:
                raw = S.auto_power_spectrums(
                    sig, freq_resolution=df, overlap=overlap,
                    window=name, window_parameter=parameter)
                self._spectra[sig.sid] = S.format_spectrum(
                    raw,
                    function_type=self.function_type.currentText(),
                    display_option=self.display_option.currentText(),
                    weighting=self.weighting.currentText())
            except ValueError as exc:
                failures.append(f"{sig.name}: {exc}")

        self._refresh_list()
        self._replot()
        self._update_energy_band()
        if failures:
            self.statusBar().showMessage("  |  ".join(failures))
        else:
            message = f"{len(self._spectra)} spectrum/spectra in {self.window_name}"
            # a requested resolution finer than the record allows is clamped
            # to the whole record; say so rather than silently ignoring it
            achieved = {round(s.dt, 9) for s in self._spectra.values()}
            if achieved and not any(abs(a - df) < 1e-9 for a in achieved):
                got = ", ".join(f"{a:g}" for a in sorted(achieved))
                message += (f"  -  requested {df:g} Hz not possible with this "
                            f"record length; using {got} Hz")
            self.statusBar().showMessage(message)

    def _refresh_list(self) -> None:
        checked = {}
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            checked[item.data(0, Qt.UserRole).sid] = (
                item.checkState(0) == Qt.Checked)

        self.tree.blockSignals(True)
        self.tree.clear()
        for sig in self.store:
            spec = self._spectra.get(sig.sid)
            item = QTreeWidgetItem([
                sig.name,
                str(spec.attributes.get("FFT_Nb_Averages", "-")) if spec else "-",
                f"{spec.dt:g}" if spec else "-",
                spec.y_unit if spec else "(not computed)",
            ])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if checked.get(sig.sid, True)
                               else Qt.Unchecked)
            item.setData(0, Qt.UserRole, sig)
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)

    def _visible_sids(self) -> list[int]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                out.append(item.data(0, Qt.UserRole).sid)
        return out

    def _replot(self) -> None:
        self.plot.clear()
        if self.legend is not None:
            self.legend.clear()
        log_x = self.log_x.currentIndex() == 1
        units = set()
        for i, sid in enumerate(self._visible_sids()):
            spec = self._spectra.get(sid)
            if spec is None:
                continue
            freqs, values = spec.t, spec.y
            if log_x:
                # log10(0 Hz) is -inf; drop the DC bin as analysers do
                freqs, values = freqs[1:], values[1:]
            pen = pg.mkPen(_PEN_COLOURS[i % len(_PEN_COLOURS)], width=1)
            self.plot.plot(freqs, values, pen=pen, name=spec.name)
            units.add(spec.y_unit)
        label = units.pop() if len(units) == 1 else "Amplitude"
        self.plot.setLabel("left", label)
        self._apply_graph_options()

    def _apply_graph_options(self) -> None:
        self.plot.setLogMode(x=self.log_x.currentIndex() == 1,
                             y=self.log_y.currentIndex() == 1)
        self.plot.enableAutoRange()

    # -- energy band ---------------------------------------------------------
    def _update_energy_band(self) -> None:
        """Band RMS / power over [start, end], from the raw rms² spectrum."""
        import math

        name = self.window_name_selected
        parameter = (self.window_parameter.value()
                     if self.window_parameter.isEnabled() else math.nan)
        lo, hi = self.band_start.value(), self.band_end.value()
        if hi < lo:
            lo, hi = hi, lo

        rows = []
        for sig in self.store:
            if sig.sid not in self._spectra:
                continue
            try:
                raw = S.auto_power_spectrums(
                    sig, freq_resolution=self.freq_resolution.value(),
                    overlap=self.overlap.value() / 100.0,
                    window=name, window_parameter=parameter)
            except ValueError:
                continue
            power = S.band_power(raw, lo, hi)
            rows.append((sig.name, math.sqrt(max(power, 0.0)), power,
                         sig.y_unit))

        self.band_table.setRowCount(len(rows))
        for r, (name_, rms, power, unit) in enumerate(rows):
            self.band_table.setItem(r, 0, QTableWidgetItem(name_))
            self.band_table.setItem(r, 1, QTableWidgetItem(
                f"{rms:.6g} {unit}".strip()))
            self.band_table.setItem(r, 2, QTableWidgetItem(
                f"{power:.6g} {unit}²".strip()))

    def copy_band_table(self) -> None:
        lines = ["Signal\tBand RMS\tBand Power"]
        for r in range(self.band_table.rowCount()):
            cells = [self.band_table.item(r, c).text() if
                     self.band_table.item(r, c) else "" for c in range(3)]
            lines.append("\t".join(cells))
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage("Energy band table copied to clipboard")

    def copy_spectra(self) -> None:
        visible = [self._spectra[s] for s in self._visible_sids()
                   if s in self._spectra]
        if not visible:
            QMessageBox.information(self, "Export", "No spectra to export.")
            return
        header = ["Frequency (Hz)"] + [s.name for s in visible]
        lines = ["\t".join(header)]
        freqs = visible[0].t
        for i, f in enumerate(freqs):
            lines.append("\t".join([f"{f:g}"]
                                   + [f"{s.y[i]:g}" for s in visible]))
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage(
            f"{len(visible)} spectrum/spectra copied to clipboard")

    # -- actions -------------------------------------------------------------
    def _update_import_action(self) -> None:
        sources = [w for w in self.manager.others(self) if hasattr(w, "store")]
        self.import_action.setEnabled(bool(sources))

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

    def new_window(self) -> FFTWindow:
        window = FFTWindow(self.manager)
        window.show()
        return window

    def duplicate_window(self) -> FFTWindow:
        window = FFTWindow(self.manager)
        for sig in self.store:
            window.store.add(sig.copy())
        window.freq_resolution.setValue(self.freq_resolution.value())
        window.overlap.setValue(self.overlap.value())
        window.window_box.setCurrentIndex(self.window_box.currentIndex())
        window.function_type.setCurrentIndex(self.function_type.currentIndex())
        window.display_option.setCurrentIndex(self.display_option.currentIndex())
        window.weighting.setCurrentIndex(self.weighting.currentIndex())
        window.show()
        return window

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0:
            self._replot()

    def closeEvent(self, event) -> None:
        self.manager.unregister(self)
        self.bridge.close()
        super().closeEvent(event)
