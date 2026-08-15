"""Time-Frequency window - port of ``Time Frequency Analysis (V1.25).vit``.

The panel's defining layout: a spectrogram in the middle with a movable
cross-hair cursor, a **Time Section** (spectrum at the cursor's time) and a
**Frequency Section** (level over time at the cursor's frequency) flanking
it. One signal is analysed at a time, chosen from the Channel selector.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QGuiApplication, QPalette
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
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..processing.dsp import timefreq as TF
from ..processing.dsp.windows import WINDOW_NAMES
from ..processing.model.signal import Signal
from ..processing.model.store import SignalStore
from .bridge import StoreBridge, WindowManager
from .dialogs import ImportFromWindowDialog
from .fft_analysis import _WINDOW_LABELS
from .plotting import SpwbPlot, curve_pen

__all__ = ["TimeFrequencyWindow"]

BLOCK_SIZES = (128, 256, 512, 1024, 2048, 4096, 8192)

# colour maps for the Color Table control, mapped to pyqtgraph names
_COLOR_MAPS = {
    "rainbow": "CET-R4", "fire": "CET-L4", "gray": "CET-L1",
    "viridis": "viridis",
}


class TimeFrequencyWindow(QMainWindow):
    def __init__(self, manager: WindowManager,
                 store: SignalStore | None = None) -> None:
        super().__init__()
        self.manager = manager
        self.bridge = StoreBridge(store)
        self.window_name = manager.register(self)
        self.setWindowTitle(f"SPWB - Time Frequency Analysis  "
                            f"[{self.window_name}]")
        self.resize(1240, 800)

        self._spectrogram: TF.Spectrogram | None = None
        self._display: TF.Spectrogram | None = None

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
        palette = self.palette()
        self._bg = palette.color(QPalette.Base)
        self._fg = palette.color(QPalette.WindowText)

        self.channel = QComboBox()
        self.channel.currentIndexChanged.connect(self.recompute)

        # --- the spectrogram ------------------------------------------
        self.image_plot = self._make_plot("Time (sec)", "Frequency (Hz)")
        self.image = pg.ImageItem()
        self.image_plot.addItem(self.image)
        self.colorbar = self.image_plot.plotItem.addColorBar(
            self.image, colorMap="CET-R4", interactive=False)

        self.v_line = pg.InfiniteLine(angle=90, movable=True,
                                      pen=curve_pen("#ffcc00"))
        self.h_line = pg.InfiniteLine(angle=0, movable=True,
                                      pen=curve_pen("#ffcc00"))
        self.image_plot.addItem(self.v_line)
        self.image_plot.addItem(self.h_line)
        self.v_line.sigPositionChanged.connect(self._update_sections)
        self.h_line.sigPositionChanged.connect(self._update_sections)
        self.image_plot.scene().sigMouseClicked.connect(self._on_click)

        self.cursor_label = QLabel("Cursor: -")

        # --- the two cross sections -----------------------------------
        self.time_section_plot = self._make_plot("Frequency (Hz)", "Amplitude")
        self.freq_section_plot = self._make_plot("Time (sec)", "Amplitude")
        self.time_curve = self.time_section_plot.plot(
            pen=curve_pen("#1f77b4"))
        self.freq_curve = self.freq_section_plot.plot(
            pen=curve_pen("#d62728"))

        sections = QSplitter(Qt.Horizontal)
        sections.addWidget(self._titled("Time Section (spectrum at cursor)",
                                        self.time_section_plot))
        sections.addWidget(self._titled("Frequency Section (level over time)",
                                        self.freq_section_plot))
        sections.setSizes([500, 500])

        centre = QSplitter(Qt.Vertical)
        centre.addWidget(self._titled("Spectrogram", self.image_plot))
        centre.addWidget(sections)
        centre.setStretchFactor(0, 2)
        centre.setSizes([460, 260])

        top = QHBoxLayout()
        top.addWidget(QLabel("Channel:"))
        top.addWidget(self.channel, 1)
        top.addWidget(self.cursor_label)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(6, 6, 6, 6)
        body_layout.addLayout(top)
        body_layout.addWidget(centre, 1)
        body_layout.addWidget(self._build_controls())
        self.setCentralWidget(body)
        self.statusBar().showMessage("Import a signal to analyse")

    def _make_plot(self, x_label: str, y_label: str) -> SpwbPlot:
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
        self.block_size = QComboBox()
        for size in BLOCK_SIZES:
            self.block_size.addItem(str(size), size)
        self.block_size.setCurrentText("1024")

        self.overlap = QSpinBox()
        self.overlap.setRange(0, 95)
        self.overlap.setValue(75)
        self.overlap.setSuffix(" %")
        self.overlap.setToolTip("Overlap between blocks; sets the hop")

        self.window_box = QComboBox()
        for name in WINDOW_NAMES:
            self.window_box.addItem(_WINDOW_LABELS.get(name, name), name)
        self.window_box.setCurrentIndex(WINDOW_NAMES.index("hanning"))

        self.normalize = QCheckBox("Norm Signal")

        self.db_on = QCheckBox("dB")
        self.db_on.setChecked(True)
        self.dynamic_range = QDoubleSpinBox()
        self.dynamic_range.setRange(10.0, 300.0)
        self.dynamic_range.setValue(100.0)
        self.dynamic_range.setSuffix(" dB")
        self.dynamic_range.setToolTip("Colour scale span below the peak")

        self.color_table = QComboBox()
        self.color_table.addItems(TF.COLOR_TABLES)

        analysis = QGroupBox("STFT Parameters")
        analysis_form = QFormLayout(analysis)
        analysis_form.addRow("FFT block size:", self.block_size)
        analysis_form.addRow("Overlap:", self.overlap)
        analysis_form.addRow("Window type:", self.window_box)
        analysis_form.addRow("", self.normalize)

        display = QGroupBox("Display")
        display_form = QFormLayout(display)
        display_form.addRow("Amplitude:", self.db_on)
        display_form.addRow("Dynamic range:", self.dynamic_range)
        display_form.addRow("Color Table:", self.color_table)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(analysis)
        layout.addWidget(display)
        layout.addStretch(1)

        for widget in (self.block_size, self.window_box):
            widget.currentIndexChanged.connect(self.recompute)
        self.overlap.valueChanged.connect(self.recompute)
        self.normalize.stateChanged.connect(self.recompute)
        self.db_on.stateChanged.connect(self._redraw)
        self.dynamic_range.valueChanged.connect(self._redraw)
        self.color_table.currentIndexChanged.connect(self._apply_color_table)
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
        act = QAction("Export sections to clipboard", self)
        act.triggered.connect(self.copy_sections)
        signals_menu.addAction(act)
        act = QAction("Exit", self)
        act.triggered.connect(self.close)
        signals_menu.addAction(act)

        window_menu = bar.addMenu("&Window")
        act = QAction("New TFA Window", self)
        act.setShortcut("Ctrl+N")
        act.triggered.connect(lambda: TimeFrequencyWindow(self.manager).show())
        window_menu.addAction(act)

    # -- data ----------------------------------------------------------------
    def _on_store_changed(self) -> None:
        current = self.channel.currentData()
        self.channel.blockSignals(True)
        self.channel.clear()
        for sig in self.store:
            self.channel.addItem(sig.name, sig)
        if current is not None:
            index = self.channel.findData(current)
            if index >= 0:
                self.channel.setCurrentIndex(index)
        self.channel.blockSignals(False)
        self.recompute()

    @property
    def selected_signal(self) -> Signal | None:
        return self.channel.currentData()

    def recompute(self) -> None:
        signal = self.selected_signal
        if signal is None:
            self._spectrogram = None
            self.image.clear()
            self.time_curve.setData([], [])
            self.freq_curve.setData([], [])
            self.statusBar().showMessage("Import a signal to analyse")
            return

        block = self.block_size.currentData()
        hop = max(1, int(round(block * (1.0 - self.overlap.value() / 100.0))))
        try:
            self._spectrogram = TF.stft_spectrogram(
                signal, block_size=block, hop=hop,
                window=self.window_box.currentData(),
                normalize=self.normalize.isChecked())
        except ValueError as exc:
            self._spectrogram = None
            self.image.clear()
            self.time_curve.setData([], [])
            self.freq_curve.setData([], [])
            self.statusBar().showMessage(str(exc))
            return

        self.statusBar().showMessage(
            f"{self._spectrogram.n_frames} x {self._spectrogram.n_bins} "
            f"(time x frequency)  -  df = {self._spectrogram.df:g} Hz, "
            f"dt = {self._spectrogram.dt * 1e3:g} ms")
        self._redraw(recentre=True)

    def _redraw(self, *_args, recentre: bool = False) -> None:
        spec = self._spectrogram
        if spec is None:
            return
        self._display = (spec.to_db(dynamic_range=self.dynamic_range.value())
                         if self.db_on.isChecked() else spec)
        data = self._display.data

        self.image.setImage(data, autoLevels=False)
        # map image pixels onto (time, frequency) axes
        self.image.setRect(pg.QtCore.QRectF(
            float(spec.times[0]), float(spec.freqs[0]),
            float(spec.times[-1] - spec.times[0]) or 1.0,
            float(spec.freqs[-1] - spec.freqs[0]) or 1.0))
        low, high = float(data.min()), float(data.max())
        if low == high:
            high = low + 1.0
        self.image.setLevels((low, high))
        self.colorbar.setLevels((low, high))
        self.colorbar.setLabel("right", self._display.y_unit)
        self._apply_color_table()

        if recentre:
            self.v_line.setValue(float(np.median(spec.times)))
            self.h_line.setValue(float(np.median(spec.freqs)))
        self._update_sections()

    def _apply_color_table(self) -> None:
        name = _COLOR_MAPS.get(self.color_table.currentText(), "viridis")
        try:
            cmap = pg.colormap.get(name)
        except Exception:                      # pragma: no cover - pg version
            cmap = pg.colormap.get("viridis")
        self.image.setColorMap(cmap)
        self.colorbar.setColorMap(cmap)

    def _on_click(self, event) -> None:
        """Click anywhere on the spectrogram to move the cross-hair."""
        if self._spectrogram is None:
            return
        view = self.image_plot.plotItem.vb
        if not self.image_plot.sceneBoundingRect().contains(event.scenePos()):
            return
        point = view.mapSceneToView(event.scenePos())
        self.v_line.setValue(point.x())
        self.h_line.setValue(point.y())

    def _update_sections(self) -> None:
        spec = self._display
        if spec is None:
            return
        time = float(self.v_line.value())
        freq = float(self.h_line.value())
        time_section = spec.time_section(time)
        freq_section = spec.frequency_section(freq)
        self.time_curve.setData(time_section.t, time_section.y)
        self.freq_curve.setData(freq_section.t, freq_section.y)

        snapped_t = time_section.attributes["TFA_Time"]
        snapped_f = freq_section.attributes["TFA_Frequency"]
        i = int(np.argmin(np.abs(spec.times - snapped_t)))
        j = int(np.argmin(np.abs(spec.freqs - snapped_f)))
        self.cursor_label.setText(
            f"Cursor:  {snapped_t:.4g} s,  {snapped_f:.6g} Hz  =  "
            f"{spec.data[i, j]:.4g} {spec.y_unit}")

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

    def copy_sections(self) -> None:
        spec = self._display
        if spec is None:
            QMessageBox.information(self, "Export", "Nothing to export.")
            return
        time_section = spec.time_section(float(self.v_line.value()))
        freq_section = spec.frequency_section(float(self.h_line.value()))
        lines = [f"Time Section\t{time_section.name}",
                 f"Frequency (Hz)\tAmplitude ({spec.y_unit})"]
        lines += [f"{f:g}\t{v:g}" for f, v in zip(time_section.t,
                                                  time_section.y, strict=True)]
        lines += ["", f"Frequency Section\t{freq_section.name}",
                  f"Time (sec)\tAmplitude ({spec.y_unit})"]
        lines += [f"{t:g}\t{v:g}" for t, v in zip(freq_section.t,
                                                  freq_section.y, strict=True)]
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage("Both sections copied to clipboard")

    def closeEvent(self, event) -> None:
        self.manager.unregister(self)
        self.bridge.close()
        super().closeEvent(event)
