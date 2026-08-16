"""Time Processing window - port of ``Time Data Processing (V1.25).vit``.

The hub window of SPWB: loads and saves time signals, and hands them to the
analysis tools. Menu structure follows the original runtime menu
(``TDP.rtm``): File / Signals / Window / About.

Compared with the LabVIEW original this window is deliberately thinner - the
analysis tabs (Scale, Stats, TV Metrics, Signal Processing) are still to be
ported. What is complete is the part that validates the architecture: the
per-window signal store, plotting, TDMS import, and the multi-instance
signal sharing that was the application's defining feature.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..processing.model.signal import Signal
from ..processing.model.store import SignalStore
from . import settings
from .analysis_tabs import ScaleSignalsTab, StatsTab, TVMetricsTab
from .bridge import StoreBridge, WindowManager
from .dialogs import ChannelSelectDialog, CreateSignalDialog, ImportFromWindowDialog
from .plotting import SpwbPlot, curve_pen

__all__ = ["TimeProcessingWindow"]



class TimeProcessingWindow(QMainWindow):
    def __init__(self, manager: WindowManager,
                 store: SignalStore | None = None) -> None:
        super().__init__()
        self.manager = manager
        self.bridge = StoreBridge(store)
        self.window_name = manager.register(self)
        self.setWindowTitle(f"SPWB - Time Data Processing  [{self.window_name}]")
        self.resize(1100, 700)

        self._build_ui()
        self._build_menus()

        self.bridge.changed.connect(self._refresh_list)
        self.bridge.changed.connect(self._refresh_tabs)
        self.manager.windows_changed.connect(self._update_import_action)
        self._refresh_list()
        self._refresh_tabs()
        self._update_import_action()

    # -- convenience ---------------------------------------------------------
    @property
    def store(self) -> SignalStore:
        return self.bridge.store

    # -- construction --------------------------------------------------------
    def _build_ui(self) -> None:
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Signal", "Samples", "Fs (Hz)",
                                   "Duration (s)", "Unit"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, self.tree.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete_selected)
        hide_btn = QPushButton("Delete All Invisible Signals")
        hide_btn.clicked.connect(self.delete_invisible)
        buttons = QHBoxLayout()
        buttons.addWidget(delete_btn)
        buttons.addWidget(hide_btn)
        buttons.addStretch(1)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select a signal to see its attributes")

        # The signal list and the attributes box get a splitter of their own.
        # A demo file's attributes can run to a dozen lines, and a session can
        # hold a dozen signals, so which of the two needs the room changes
        # from minute to minute - that is the splitter's job, not a fixed
        # height's. Dragging it fully shut hides the attributes entirely.
        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.addWidget(QLabel("Signals in this window"))
        list_layout.addWidget(self.tree, 1)
        list_layout.addLayout(buttons)

        details_panel = QWidget()
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(0, 6, 0, 0)
        details_layout.addWidget(QLabel("Attributes"))
        details_layout.addWidget(self.details, 1)

        left = QSplitter(Qt.Vertical)
        left.setContentsMargins(6, 6, 6, 6)
        left.addWidget(list_panel)
        left.addWidget(details_panel)
        left.setStretchFactor(0, 1)     # the list takes new space
        left.setStretchFactor(1, 0)
        left.setSizes([440, 170])       # about the old fixed proportions

        self.plot = SpwbPlot()
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setLabel("left", "Amplitude")
        self.legend = self.plot.addLegend(offset=(-10, 10))

        # the panel's analysis tabs, below the plot
        self.tabs = QTabWidget()
        self.scale_tab = ScaleSignalsTab(self.store)
        self.stats_tab = StatsTab(self.store)
        self.tvm_tab = TVMetricsTab(self.store)
        self.tabs.addTab(self.scale_tab, "Scale Signals")
        self.tabs.addTab(self.stats_tab, "Stats")
        self.tabs.addTab(self.tvm_tab, "TV Metrics")
        self.tabs.currentChanged.connect(lambda _: self._refresh_tabs())

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.plot)
        right.addWidget(self.tabs)
        right.setStretchFactor(0, 1)
        right.setSizes([440, 260])

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 680])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready")

    def _refresh_tabs(self) -> None:
        """Rebuild only the visible tab: the others rebuild when shown."""
        current = self.tabs.currentWidget()
        if current is not None:
            current.refresh()

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        open_menu = file_menu.addMenu("Open ...")
        # HDF5 first: it is the native format of the Python port
        act = QAction("SPWB / HDF5 (*.h5, *.hdf5)", self)
        act.setShortcut(QKeySequence.Open)
        act.triggered.connect(self.open_hdf5)
        open_menu.addAction(act)
        open_menu.addSeparator()
        act = QAction("National Instruments (*.tdms)", self)
        act.triggered.connect(self.open_tdms)
        open_menu.addAction(act)
        act = QAction("Wave Files (*.wav)", self)
        act.triggered.connect(self.open_wave)
        open_menu.addAction(act)
        act = QAction("Text / CSV (*.csv, *.txt)", self)
        act.triggered.connect(self.open_text)
        open_menu.addAction(act)
        open_menu.addSeparator()
        act = QAction("Select Multiple Wave Files", self)
        act.triggered.connect(self.open_multiple_waves)
        open_menu.addAction(act)
        # read-only formats, below the ones we also write
        open_menu.addSeparator()
        act = QAction("MTS RPC-III (*.rsp)", self)
        act.triggered.connect(self.open_rpc)
        open_menu.addAction(act)
        act = QAction("HEAD acoustics (*.hdf)", self)
        act.triggered.connect(self.open_head_hdf)
        open_menu.addAction(act)

        save_menu = file_menu.addMenu("Save ...")
        act = QAction("SPWB / HDF5 (*.h5)", self)
        act.setShortcut(QKeySequence.Save)
        act.triggered.connect(self.save_hdf5)
        save_menu.addAction(act)
        save_menu.addSeparator()
        act = QAction("National Instruments (*.tdms)", self)
        act.triggered.connect(self.save_tdms)
        save_menu.addAction(act)
        act = QAction("Wave Files (*.wav)", self)
        act.triggered.connect(self.save_wave)
        save_menu.addAction(act)
        act = QAction("Text / CSV for Excel (*.csv)", self)
        act.triggered.connect(self.save_text)
        save_menu.addAction(act)

        file_menu.addSeparator()
        act = QAction("Exit", self)
        act.triggered.connect(self.close)
        file_menu.addAction(act)

        signals_menu = bar.addMenu("&Signals")
        act = QAction("Create ...", self)
        act.triggered.connect(self.create_signal)
        signals_menu.addAction(act)
        signals_menu.addSeparator()
        import_menu = signals_menu.addMenu("Import Signals ...")
        self.import_action = QAction("Another Window", self)
        self.import_action.triggered.connect(self.import_from_window)
        import_menu.addAction(self.import_action)
        act = QAction("From TDMS File (*.tdms)", self)
        act.triggered.connect(self.open_tdms)
        import_menu.addAction(act)
        act = QAction("From Wave File (*.wav)", self)
        act.triggered.connect(self.open_wave)
        import_menu.addAction(act)
        act = QAction("From RPC-III File (*.rsp)", self)
        act.triggered.connect(self.open_rpc)
        import_menu.addAction(act)
        act = QAction("From HEAD acoustics File (*.hdf)", self)
        act.triggered.connect(self.open_head_hdf)
        import_menu.addAction(act)

        # "Spectrums" on the original front panel: hand the selected (or all
        # visible) signals to a new FFT Analysis window.
        analysis_menu = bar.addMenu("&Analysis")
        act = QAction("Spectrums (FFT) ...", self)
        act.setShortcut("Ctrl+F")
        act.triggered.connect(self.open_fft_window)
        analysis_menu.addAction(act)
        act = QAction("Transfer Functions ...", self)
        act.setShortcut("Ctrl+T")
        act.triggered.connect(self.open_tf_window)
        analysis_menu.addAction(act)
        act = QAction("Time Frequency Analysis ...", self)
        act.setShortcut("Ctrl+G")
        act.triggered.connect(self.open_tfa_window)
        analysis_menu.addAction(act)
        act = QAction("Adaptive Filtering (LMS) ...", self)
        act.setShortcut("Ctrl+L")
        act.triggered.connect(self.open_lms_window)
        analysis_menu.addAction(act)

        window_menu = bar.addMenu("&Window")
        act = QAction("New (empty)", self)
        act.setShortcut("Ctrl+N")
        act.triggered.connect(self.new_window)
        window_menu.addAction(act)
        act = QAction("Duplicate Current Window", self)
        act.triggered.connect(self.duplicate_window)
        window_menu.addAction(act)

        about_menu = bar.addMenu("&About")
        act = QAction("About SPWB", self)
        act.triggered.connect(self.show_about)
        about_menu.addAction(act)

    # -- list / plot ---------------------------------------------------------
    def _refresh_list(self) -> None:
        checked = {}
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            sig = item.data(0, Qt.UserRole)
            checked[sig.sid] = item.checkState(0) == Qt.Checked

        self.tree.blockSignals(True)
        self.tree.clear()
        for sig in self.store:
            item = QTreeWidgetItem([
                sig.name, str(sig.n_samples), f"{sig.fs:g}",
                f"{sig.duration:.4g}", sig.y_unit or "-",
            ])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if checked.get(sig.sid, True)
                               else Qt.Unchecked)
            item.setData(0, Qt.UserRole, sig)
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)
        self._replot()
        self.statusBar().showMessage(
            f"{len(self.store)} signal(s) in {self.window_name}")

    def _visible_signals(self) -> list[Signal]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                out.append(item.data(0, Qt.UserRole))
        return out

    def _replot(self) -> None:
        self.plot.clear()
        if self.legend is not None:
            self.legend.clear()
        units = set()
        for i, sig in enumerate(self._visible_signals()):
            self.plot.plot(sig.t, sig.y, pen=curve_pen(i), name=sig.name)
            if sig.y_unit:
                units.add(sig.y_unit)
        label = units.pop() if len(units) == 1 else ""
        self.plot.setLabel("left", "Amplitude", units=label or None)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0:
            self._replot()

    def _update_import_action(self) -> None:
        """Grey out 'Import from Another Window' when this is the only one."""
        sources = [w for w in self.manager.others(self)
                   if isinstance(w, TimeProcessingWindow)]
        self.import_action.setEnabled(bool(sources))
        self.import_action.setToolTip(
            "" if sources else "Open a second window to share signals")

    def _on_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            self.details.clear()
            return
        sig: Signal = items[0].data(0, Qt.UserRole)
        lines = [f"{sig.name}",
                 f"  samples : {sig.n_samples}",
                 f"  fs      : {sig.fs:g} Hz   (dt = {sig.dt:g} s)",
                 f"  t0      : {sig.t0:g} s",
                 f"  duration: {sig.duration:g} s",
                 f"  Y unit  : {sig.y_unit or '-'}",
                 f"  X unit  : {sig.x_unit or '-'}",
                 "  attributes:"]
        for key, value in sig.attributes.items():
            if key in ("TDMS", "RPC", "HDF"):
                value = f"<{len(value)} raw {key} properties>"
            text = str(value)
            if len(text) > 70:
                text = text[:67] + "..."
            lines.append(f"    {key}: {text}")
        self.details.setPlainText("\n".join(lines))

    # -- actions -------------------------------------------------------------
    def open_tdms(self) -> None:
        path = settings.open_file(
            self, "Open TDMS File", "tdms", "National Instruments (*.tdms)")
        if not path:
            return
        try:
            from ..processing.io import read_tdms, tdms_contents
            channels = tdms_contents(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open TDMS", f"Could not read file:\n{exc}")
            return
        if not channels:
            QMessageBox.information(self, "Open TDMS", "No channels in this file.")
            return

        dialog = ChannelSelectDialog(channels, self)
        if dialog.exec() != ChannelSelectDialog.Accepted:
            return
        selected = dialog.selected_paths()
        if not selected:
            return

        dt = None
        if dialog.needs_dt():
            fs, ok = QInputDialog.getDouble(
                self, "Sample rate needed",
                "Some selected channels carry no timing information.\n"
                "Sample rate to assume (Hz):", 51200.0, 1e-6, 1e9, 3)
            if not ok:
                return
            dt = 1.0 / fs

        try:
            signals = read_tdms(path, select=selected, dt=dt,
                                decorate_names=len(self.store) > 0)
        except Exception as exc:
            QMessageBox.critical(self, "Open TDMS", f"Could not import:\n{exc}")
            return
        for sig in signals:
            self.store.add(sig)
        self.statusBar().showMessage(
            f"Imported {len(signals)} signal(s) from {Path(path).name}")

    def save_tdms(self) -> None:
        if not len(self.store):
            QMessageBox.information(self, "Save TDMS", "No signals to save.")
            return
        path = settings.save_file(
            self, "Save TDMS File", "tdms", "National Instruments (*.tdms)")
        if not path:
            return
        try:
            from ..processing.io import write_tdms
            write_tdms(path, list(self.store))
        except Exception as exc:
            QMessageBox.critical(self, "Save TDMS", f"Could not write file:\n{exc}")
            return
        self.statusBar().showMessage(f"Saved {len(self.store)} signal(s) "
                                     f"to {Path(path).name}")

    def open_text(self) -> None:
        path = settings.open_file(
            self, "Open Text / CSV File", "text",
            "Text and CSV (*.csv *.txt *.dat *.asc);;All files (*)")
        if not path:
            return
        from ..processing.io import read_text, text_contents

        self._import_channels("Open Text / CSV", path, text_contents,
                              read_text)

    def save_text(self) -> None:
        signals = self._visible_signals()
        if not signals:
            QMessageBox.information(self, "Save Text / CSV",
                                    "No signals to save.")
            return
        path = settings.save_file(
            self, "Save Text / CSV File", "text",
            "CSV (*.csv);;Text (*.txt)")
        if not path:
            return
        from ..processing.io import LOCALES, write_text

        # A French- or German-locale Excel reads "1,5" as a number and needs
        # ";" between fields; a dot-decimal file lands in one text column
        # there. Ask rather than guess, because the right answer depends on
        # the machine the file is opened on, not the one writing it.
        choice, ok = QInputDialog.getItem(
            self, "Number format",
            "Which number format should Excel expect?",
            ["Comma separated, decimal point  (1,234.5)",
             "Semicolon separated, decimal comma  (1;234,5)"], 0, False)
        if not ok:
            return
        locale = "en" if choice.startswith("Comma") else "fr"
        assert locale in LOCALES

        try:
            written = write_text(path, signals, locale=locale)
        except Exception as exc:
            QMessageBox.critical(self, "Save Text / CSV",
                                 f"Could not write:\n{exc}")
            return
        self.statusBar().showMessage(
            f"Saved {len(signals)} signal(s) to {written.name} - opens "
            f"directly in Excel and LibreOffice")

    def open_rpc(self) -> None:
        path = settings.open_file(
            self, "Open RPC-III File", "rpc",
            "MTS RPC-III (*.rsp);;All files (*)")
        if not path:
            return
        from ..processing.io import read_rpc, rpc_contents

        self._import_channels("Open RPC-III", path, rpc_contents, read_rpc)

    def open_head_hdf(self) -> None:
        path = settings.open_file(
            self, "Open HEAD acoustics File", "head_hdf",
            "HEAD acoustics (*.hdf);;All files (*)")
        if not path:
            return
        from ..processing.io import head_hdf_contents, read_head_hdf

        self._import_channels("Open HEAD acoustics", path,
                              head_hdf_contents, read_head_hdf)

    def _import_channels(self, title: str, path: str, contents, reader) -> None:
        """Shared list-channels -> pick -> import flow for read-only formats.

        The reader errors are shown verbatim: for HEAD acoustics files the
        message is an install instruction, which is the actual fix.
        """
        try:
            channels = contents(path)
        except Exception as exc:
            QMessageBox.critical(self, title, f"Could not read file:\n{exc}")
            return
        if not channels:
            QMessageBox.information(self, title, "No channels in this file.")
            return

        dialog = ChannelSelectDialog(channels, self)
        if dialog.exec() != ChannelSelectDialog.Accepted:
            return
        selected = dialog.selected_paths()
        if not selected:
            return

        kwargs = {}
        if dialog.needs_dt():
            fs, ok = QInputDialog.getDouble(
                self, "Sample rate needed",
                "Some selected channels carry no timing information.\n"
                "Sample rate to assume (Hz):", 51200.0, 1e-6, 1e9, 3)
            if not ok:
                return
            kwargs["dt"] = 1.0 / fs

        try:
            signals = reader(path, select=selected,
                             decorate_names=len(self.store) > 0, **kwargs)
        except Exception as exc:
            QMessageBox.critical(self, title, f"Could not import:\n{exc}")
            return
        for sig in signals:
            self.store.add(sig)
        self.statusBar().showMessage(
            f"Imported {len(signals)} signal(s) from {Path(path).name}")

    def open_hdf5(self) -> None:
        path = settings.open_file(
            self, "Open SPWB / HDF5 File", "hdf5",
            "SPWB / HDF5 (*.h5 *.hdf5);;All files (*)")
        if not path:
            return
        from ..processing.io import read_hdf5

        try:
            signals = read_hdf5(path, decorate_names=len(self.store) > 0)
        except Exception as exc:
            QMessageBox.critical(self, "Open HDF5",
                                 f"Could not read:\n{exc}")
            return
        for sig in signals:
            self.store.add(sig)
        self.statusBar().showMessage(
            f"Imported {len(signals)} signal(s) from {Path(path).name}")

    def save_hdf5(self) -> None:
        signals = self._visible_signals()
        if not signals:
            QMessageBox.information(self, "Save HDF5", "No signals to save.")
            return
        path = settings.save_file(
            self, "Save SPWB / HDF5 File", "hdf5", "SPWB / HDF5 (*.h5)")
        if not path:
            return
        from ..processing.io import write_hdf5

        try:
            written = write_hdf5(path, signals)
        except Exception as exc:
            QMessageBox.critical(self, "Save HDF5",
                                 f"Could not write:\n{exc}")
            return
        self.statusBar().showMessage(
            f"Saved {len(signals)} signal(s) to {written.name} - readable by "
            f"MATLAB, Julia and any HDF5 tool")

    def open_wave(self) -> None:
        path = settings.open_file(
            self, "Open Wave File", "wave", "Wave Files (*.wav)")
        if path:
            self._load_waves([path])

    def open_multiple_waves(self) -> None:
        paths = settings.open_files(
            self, "Select Multiple Wave Files", "wave",
            "Wave Files (*.wav)")
        if paths:
            self._load_waves(paths)

    def _load_waves(self, paths: list[str]) -> None:
        from ..processing.io import read_waves

        try:
            signals = read_waves(paths,
                                 decorate_names=len(self.store) > 0)
        except Exception as exc:
            QMessageBox.critical(self, "Open Wave File",
                                 f"Could not read:\n{exc}")
            return
        scaled = sum(1 for s in signals
                     if s.attributes.get("WAV Scale Factor", 1.0) != 1.0)
        for sig in signals:
            self.store.add(sig)
        message = f"Imported {len(signals)} signal(s) from {len(paths)} file(s)"
        if scaled:
            message += f"  -  {scaled} carried a scale factor in the file name"
        else:
            message += "  -  no scale factor in the file name(s); data is +-1"
        self.statusBar().showMessage(message)

    def save_wave(self) -> None:
        from ..processing.io import SAVE_OPTIONS, write_wave

        signals = self._visible_signals()
        if not signals:
            QMessageBox.information(self, "Save Wave", "No signals to save.")
            return
        rates = {round(s.fs, 6) for s in signals}
        if len(rates) > 1:
            listed = ", ".join(f"{r:g}" for r in sorted(rates))
            QMessageBox.warning(
                self, "Save Wave",
                "A WAV file holds one sample rate, but the visible signals "
                f"use {len(rates)}: {listed} Hz.\n\n"
                "Resample them first, or hide all but one rate.")
            return

        option = SAVE_OPTIONS[0]
        if len(signals) > 1:
            choices = list(SAVE_OPTIONS[:2])
            if len(signals) == 2:
                choices += list(SAVE_OPTIONS[2:])
            option, ok = QInputDialog.getItem(
                self, "Save Wave", f"{len(signals)} signals selected:",
                choices, 0, False)
            if not ok:
                return

        path = settings.save_file(
            self, "Save Wave File", "wave", "Wave Files (*.wav)")
        if not path:
            return
        try:
            written = write_wave(path, signals, save_option=option)
        except Exception as exc:
            QMessageBox.critical(self, "Save Wave",
                                 f"Could not write:\n{exc}")
            return
        self.statusBar().showMessage(
            f"Wrote {len(written)} file(s); the scale factor is in the "
            f"file name so units survive the round trip")

    def create_signal(self) -> None:
        dialog = CreateSignalDialog(self)
        if dialog.exec() == CreateSignalDialog.Accepted:
            self.store.add(dialog.build())

    def import_from_window(self) -> None:
        sources = [w for w in self.manager.others(self)
                   if isinstance(w, TimeProcessingWindow)]
        if not sources:
            QMessageBox.information(self, "Import Signals",
                                    "No other window is open.")
            return
        dialog = ImportFromWindowDialog(sources, self)
        if dialog.exec() != ImportFromWindowDialog.Accepted:
            return
        imported = dialog.selected_signals()
        for sig in imported:
            if sig.sid in self.store:
                continue
            self.store.add(sig)
        self.statusBar().showMessage(f"Imported {len(imported)} signal(s)")

    def delete_selected(self) -> None:
        for item in self.tree.selectedItems():
            sig: Signal = item.data(0, Qt.UserRole)
            if sig.sid in self.store:
                self.store.remove(sig.sid)

    def delete_invisible(self) -> None:
        visible = {s.sid for s in self._visible_signals()}
        for sig in list(self.store):
            if sig.sid not in visible:
                self.store.remove(sig.sid)

    def _send_to(self, window_class, title: str):
        """Open an analysis window holding copies of the chosen signals.

        Sends the selection if there is one, otherwise everything visible -
        the behaviour of the original front panel's analysis buttons.
        """
        chosen = [item.data(0, Qt.UserRole) for item in self.tree.selectedItems()]
        if not chosen:
            chosen = self._visible_signals()
        if not chosen:
            QMessageBox.information(self, title, "No signals to analyse.")
            return None
        window = window_class(self.manager)
        for sig in chosen:
            window.store.add(sig.copy())
        window.show()
        self.statusBar().showMessage(
            f"Sent {len(chosen)} signal(s) to {window.window_name}")
        return window

    def open_fft_window(self):
        """Front-panel 'Spectrums': send signals to a new FFT window."""
        from .fft_analysis import FFTWindow
        return self._send_to(FFTWindow, "Spectrums")

    def open_tf_window(self):
        """Front-panel 'Transfer Functions': send signals to a new TF window."""
        from .tf_analysis import TransferFunctionWindow
        return self._send_to(TransferFunctionWindow, "Transfer Functions")

    def open_tfa_window(self):
        """Front-panel 'TFA': send signals to a new Time-Frequency window."""
        from .tfa_analysis import TimeFrequencyWindow
        return self._send_to(TimeFrequencyWindow, "Time Frequency Analysis")

    def open_lms_window(self):
        """Send signals to a new Adaptive Filtering window."""
        from .lms_analysis import LMSWindow
        return self._send_to(LMSWindow, "Adaptive Filtering")

    def new_window(self) -> TimeProcessingWindow:
        window = TimeProcessingWindow(self.manager)
        window.show()
        return window

    def duplicate_window(self) -> TimeProcessingWindow:
        window = TimeProcessingWindow(self.manager)
        for sig in self.store:
            window.store.add(sig.copy())
        window.show()
        return window

    def show_about(self) -> None:
        from .. import __version__
        QMessageBox.about(
            self, "About SPWB",
            f"<h3>Signal Processing Work Bench</h3>"
            f"<p>Python port, version {__version__}</p>"
            f"<p>Original LabVIEW application by Charette AI Group, "
            f"open-sourced under the MIT license.</p>")

    # -- lifecycle -----------------------------------------------------------
    def closeEvent(self, event) -> None:
        self.manager.unregister(self)
        self.bridge.close()
        super().closeEvent(event)
