"""The shared plot widget and its LabVIEW-style graph palette.

SPWB's LabVIEW front panels put a small palette beside every graph: pick a
tool, then use the mouse directly on the plot. Zoom-to-rectangle, zoom the
X axis, zoom the Y axis, pan, and autoscale are one click plus one drag.

pyqtgraph's defaults are different - left-drag pans, right-drag zooms, and
exact ranges come from a right-click menu - which works but means opening a
menu and typing numbers to do what used to be a drag. This module puts the
palette back.

Two pieces:

:class:`GraphViewBox`
    a :class:`pyqtgraph.ViewBox` with a *tool* setting. Pan and
    zoom-to-rectangle are pyqtgraph's own modes; the X-only and Y-only band
    zooms are implemented here, because ``RectMode`` always rescales both
    axes - it calls ``showAxRect`` and ignores ``mouseEnabled``.

:class:`SpwbPlot`
    the widget the windows actually use: a ``PlotWidget`` wired to a
    :class:`GraphViewBox`, the palette beside it, and the theming that was
    previously copy-pasted into all five analysis windows. It forwards
    unknown attributes to the inner ``PlotWidget``, so ``plot.setLabel``,
    ``plot.plot``, ``plot.clear`` and friends keep working unchanged.

The right-click menu is deliberately **kept**. The palette is for the
things a mouse does well; typing an exact range is the one thing it does
badly, and that is what the menu is good at.
"""
from __future__ import annotations

from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

__all__ = ["CURVE_WIDTH", "PEN_COLOURS", "TOOLS", "GraphViewBox", "SpwbPlot",
           "curve_pen"]

# Antialiasing is off, deliberately, and it is not a cosmetic preference.
# Qt's raster engine has a fast path for 1px cosmetic pens; any wider pen
# drawn antialiased falls off a cliff on long polylines. Measured on one
# 30-second signal at 8192 Hz (245 760 points), time to paint:
#
#     antialiased, 1px ....  0.07 s
#     antialiased, 2px ....  6.42 s     <- 94x, and it is per redraw
#     aliased,     2px ....  0.21 s
#     aliased,     2px + peak downsampling ....  0.04 s
#
# Curves are 2px so they stand out from the grid, so antialiasing had to
# go. At 2px the stair-stepping is barely visible, and on dense waveform
# data it is invisible.
pg.setConfigOptions(antialias=False)

#: Data curves are drawn thicker than the grid and axes, which pyqtgraph
#: draws 1px wide. At the same width a trace reads as part of the
#: background grid rather than as the measurement; 2px separates them
#: cleanly without looking heavy. Whole pixels on purpose - a fractional
#: width antialiases into a soft grey edge on a non-HiDPI screen.
CURVE_WIDTH = 2

#: the trace colour cycle, shared by every window so the same signal keeps
#: its colour when it is sent from one to another
PEN_COLOURS: tuple[str, ...] = (
    "#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd",
    "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f",
)


def curve_pen(colour: str | int, width: int | float = CURVE_WIDTH, **kwargs):
    """A pen for a data trace: thicker than the grid, so it stands out.

    ``colour`` may be a colour string or an index into :data:`PEN_COLOURS`,
    which wraps, so callers can pass a plain loop counter.
    """
    if isinstance(colour, int):
        colour = PEN_COLOURS[colour % len(PEN_COLOURS)]
    return pg.mkPen(colour, width=width, **kwargs)

#: tool id -> (label, tooltip). The first four are drag tools and are
#: mutually exclusive; the rest are one-shot buttons.
TOOLS: dict[str, tuple[str, str]] = {
    "pan": ("Pan", "Drag to pan the plot"),
    "rect": ("Zoom", "Drag a rectangle to zoom into it"),
    "xzoom": ("Zoom X", "Drag horizontally to zoom the X axis only"),
    "yzoom": ("Zoom Y", "Drag vertically to zoom the Y axis only"),
}

_DRAG_TOOLS = tuple(TOOLS)
_CURSORS = {
    "pan": Qt.OpenHandCursor,
    "rect": Qt.CrossCursor,
    "xzoom": Qt.SplitHCursor,
    "yzoom": Qt.SplitVCursor,
}


class GraphViewBox(pg.ViewBox):
    """A ViewBox whose left-drag follows the selected palette tool."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tool = "pan"
        self.set_tool("pan")

    @property
    def tool(self) -> str:
        return self._tool

    def set_tool(self, tool: str) -> None:
        if tool not in TOOLS:
            raise ValueError(f"unknown tool {tool!r}; known: {sorted(TOOLS)}")
        self._tool = tool
        # RectMode gives us pyqtgraph's own rubber-band zoom; the axis tools
        # draw their own band, so they sit on PanMode and are intercepted in
        # mouseDragEvent below
        self.setMouseMode(pg.ViewBox.RectMode if tool == "rect"
                          else pg.ViewBox.PanMode)
        # this also constrains the wheel, which reads the same mask
        self.setMouseEnabled(x=tool != "yzoom", y=tool != "xzoom")
        self.setCursor(_CURSORS[tool])

    # -- the two modes pyqtgraph does not have -----------------------------
    def mouseDragEvent(self, ev, axis=None) -> None:
        if (axis is not None or self._tool not in ("xzoom", "yzoom")
                or ev.button() != Qt.MouseButton.LeftButton):
            super().mouseDragEvent(ev, axis=axis)
            return

        ev.accept()
        band = self._band(ev)
        if not ev.isFinish():
            self.updateScaleBox(band.topLeft(), band.bottomRight())
            return

        self.rbScaleBox.hide()
        data = self.childGroup.mapRectFromParent(band).normalized()
        before = self._view_rect()
        if self._tool == "xzoom" and data.width() > 0:
            self.setXRange(data.left(), data.right(), padding=0)
        elif self._tool == "yzoom" and data.height() > 0:
            self.setYRange(data.top(), data.bottom(), padding=0)
        else:
            return       # a stray click: do not zoom to nothing, or record it
        self._record(before)

    def _view_rect(self) -> QRectF:
        (x0, x1), (y0, y1) = self.viewRange()
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def _record(self, before: QRectF) -> None:
        """Add this zoom to the history the Undo button walks back through.

        pyqtgraph only records the view it zooms *to*, so the very first
        zoom has nothing behind it and Undo does nothing. Seeding the
        history with the pre-zoom view fixes that, which is the behaviour
        the LabVIEW palette had.
        """
        if not self.axHistory:
            self.axHistory = [before]
            self.axHistoryPointer = 0
        self.axHistoryPointer += 1
        self.axHistory = [*self.axHistory[:self.axHistoryPointer],
                          self._view_rect()]

    def _band(self, ev) -> QRectF:
        """The rubber band: full height for an X zoom, full width for a Y."""
        start = ev.buttonDownPos(ev.button())
        now = ev.pos()
        box = self.boundingRect()
        if self._tool == "xzoom":
            corners = (QPointF(start.x(), box.top()),
                       QPointF(now.x(), box.bottom()))
        else:
            corners = (QPointF(box.left(), start.y()),
                       QPointF(box.right(), now.y()))
        return QRectF(*corners).normalized()


def _icon(draw: Callable[[QPainter], None], colour: QColor) -> QIcon:
    """Paint a 20x20 glyph, so the palette needs no image files."""
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(colour, 1.6))
    draw(painter)
    painter.end()
    return QIcon(pixmap)


def _magnifier(painter: QPainter) -> None:
    painter.drawEllipse(QPointF(8.5, 8.5), 5.5, 5.5)
    painter.drawLine(12, 12, 17, 17)


def _glyphs(colour: QColor) -> dict[str, QIcon]:
    def pan(p: QPainter) -> None:
        p.drawLine(10, 3, 10, 17)
        p.drawLine(3, 10, 17, 10)
        for dx, dy, ex, ey in ((10, 3, 7, 6), (10, 3, 13, 6),
                               (10, 17, 7, 14), (10, 17, 13, 14),
                               (3, 10, 6, 7), (3, 10, 6, 13),
                               (17, 10, 14, 7), (17, 10, 14, 13)):
            p.drawLine(dx, dy, ex, ey)

    def rect(p: QPainter) -> None:
        p.setPen(QPen(colour, 1.2, Qt.DashLine))
        p.drawRect(3, 5, 14, 10)

    def xzoom(p: QPainter) -> None:
        p.drawLine(3, 10, 17, 10)
        p.drawLine(3, 10, 7, 6)
        p.drawLine(3, 10, 7, 14)
        p.drawLine(17, 10, 13, 6)
        p.drawLine(17, 10, 13, 14)

    def yzoom(p: QPainter) -> None:
        p.drawLine(10, 3, 10, 17)
        p.drawLine(10, 3, 6, 7)
        p.drawLine(10, 3, 14, 7)
        p.drawLine(10, 17, 6, 13)
        p.drawLine(10, 17, 14, 13)

    def zoom_in(p: QPainter) -> None:
        _magnifier(p)
        p.drawLine(6, 8, 11, 8)
        p.drawLine(8, 6, 8, 11)

    def zoom_out(p: QPainter) -> None:
        _magnifier(p)
        p.drawLine(6, 8, 11, 8)

    def fit(p: QPainter) -> None:
        p.drawRect(3, 5, 14, 10)
        p.drawLine(7, 10, 13, 10)
        p.drawLine(7, 10, 9, 8)
        p.drawLine(7, 10, 9, 12)
        p.drawLine(13, 10, 11, 8)
        p.drawLine(13, 10, 11, 12)

    def undo(p: QPainter) -> None:
        p.drawArc(4, 5, 12, 11, 30 * 16, 240 * 16)
        p.drawLine(4, 10, 4, 5)
        p.drawLine(4, 5, 9, 6)

    return {name: _icon(fn, colour) for name, fn in (
        ("pan", pan), ("rect", rect), ("xzoom", xzoom), ("yzoom", yzoom),
        ("zoom_in", zoom_in), ("zoom_out", zoom_out), ("fit", fit),
        ("undo", undo))}


class SpwbPlot(QWidget):
    """A themed pyqtgraph plot with SPWB's graph palette beside it.

    Behaves like the ``PlotWidget`` it wraps: any attribute this class does
    not define is forwarded, so ``setLabel``, ``plot``, ``clear``,
    ``addItem``, ``plotItem`` and the rest are unchanged from before.
    """

    #: emitted with the tool id whenever the active drag tool changes
    tool_changed = Signal(str)

    def __init__(self, x_label: str = "", y_label: str = "",
                 parent: QWidget | None = None, *,
                 palette_visible: bool = True) -> None:
        super().__init__(parent)

        colours = self.palette()
        self._bg = colours.color(QPalette.Base)
        self._fg = colours.color(QPalette.WindowText)

        self.viewbox = GraphViewBox()
        self.plot_widget = pg.PlotWidget(viewBox=self.viewbox)
        self.plot_widget.setBackground(self._bg)
        for axis in ("bottom", "left"):
            self.plot_widget.getAxis(axis).setPen(self._fg)
            self.plot_widget.getAxis(axis).setTextPen(self._fg)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        # Draw at most a couple of points per screen pixel. "peak" keeps the
        # minimum and maximum of each bin, so the envelope and any transient
        # survive - a plain stride would drop them. Zooming in re-renders
        # from the full data, so nothing is lost, only not drawn.
        #
        # Note the matching setClipToView is deliberately *not* set: it makes
        # a curve report only the data inside the current view, which breaks
        # autoscale (the Fit button cannot see past the edges), and measuring
        # showed it contributes nothing here - downsampling alone is the win.
        self.plot_widget.plotItem.setDownsampling(auto=True, mode="peak")
        if x_label:
            self.plot_widget.setLabel("bottom", x_label)
        if y_label:
            self.plot_widget.setLabel("left", y_label)

        self.toolbar = self._build_palette()
        self.toolbar.setVisible(palette_visible)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.plot_widget, 1)

    # -- palette ------------------------------------------------------------
    def _build_palette(self) -> QWidget:
        icons = _glyphs(self._fg)
        bar = QWidget()
        column = QVBoxLayout(bar)
        column.setContentsMargins(2, 2, 0, 2)
        column.setSpacing(2)

        self._buttons: dict[str, QToolButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for tool, (label, tip) in TOOLS.items():
            button = QToolButton()
            button.setIcon(icons[tool])
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolTip(f"{label} - {tip}")
            button.setAccessibleName(label)
            button.clicked.connect(
                lambda _checked=False, name=tool: self.set_tool(name))
            self._group.addButton(button)
            column.addWidget(button)
            self._buttons[tool] = button
        self._buttons["pan"].setChecked(True)

        column.addSpacing(6)
        for name, tip, slot in (
            ("zoom_in", "Zoom in about the centre", self.zoom_in),
            ("zoom_out", "Zoom out about the centre", self.zoom_out),
            ("fit", "Autoscale to fit all data", self.autoscale),
            ("undo", "Undo the last zoom", self.undo_zoom),
        ):
            button = QToolButton()
            button.setIcon(icons[name])
            button.setAutoRaise(True)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(slot)
            column.addWidget(button)
            self._buttons[name] = button

        column.addStretch(1)
        bar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        return bar

    # -- the actions the palette drives -------------------------------------
    def set_tool(self, tool: str) -> None:
        """Select the drag tool, as clicking its palette button would."""
        self.viewbox.set_tool(tool)
        button = self._buttons.get(tool)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self.tool_changed.emit(tool)

    @property
    def tool(self) -> str:
        return self.viewbox.tool

    def zoom_in(self) -> None:
        self._scale(0.5)

    def zoom_out(self) -> None:
        self._scale(2.0)

    def _scale(self, factor: float) -> None:
        """Zoom about the centre, on whichever axes the tool allows."""
        x_on, y_on = self.viewbox.state["mouseEnabled"]
        self.viewbox.scaleBy((factor if x_on else 1.0,
                              factor if y_on else 1.0))

    def autoscale(self) -> None:
        self.viewbox.enableAutoRange()

    def undo_zoom(self) -> None:
        self.viewbox.scaleHistory(-1)

    def set_palette_visible(self, visible: bool) -> None:
        self.toolbar.setVisible(visible)

    # -- behave like the PlotWidget we wrap ---------------------------------
    def __getattr__(self, name: str):
        # only reached for attributes this class does not define; guard the
        # bootstrap case where self.plot is not assigned yet
        try:
            plot = self.__dict__["plot_widget"]
        except KeyError:
            raise AttributeError(name) from None
        return getattr(plot, name)
