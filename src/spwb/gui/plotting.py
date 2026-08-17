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

import math
from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QInputDialog,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

__all__ = [
    "CURVE_WIDTH",
    "GRID_ALPHA",
    "LEGEND_OPACITY",
    "PEN_COLOURS",
    "TOOLS",
    "EditableAxis",
    "GraphViewBox",
    "SpwbPlot",
    "curve_pen",
    "limit_end_at",
]

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

#: Grid opacity. Kept low so the grid reads as a background reference and
#: the traces sit in front of it; it still gives the eye a scale.
GRID_ALPHA = 0.2

#: Legend backing, 0-255. Nearly opaque so labels stay readable over a
#: dense trace, but not fully - a curve passing behind stays faintly
#: visible, which keeps the legend reading as an overlay rather than a
#: hole punched in the plot.
LEGEND_OPACITY = 235
#: the legend's border, much fainter than the text it encloses
LEGEND_BORDER_ALPHA = 90

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


def limit_end_at(text_specs, pos, horizontal: bool) -> str | None:
    """Which axis limit the point ``pos`` is on: "min", "max" or neither.

    ``text_specs`` are the ``(rect, flags, text)`` triples pyqtgraph builds
    for the tick labels. Only the two extreme labels count, because those
    are the ones that *are* the axis limits - LabVIEW let you edit the first
    and last tick and nothing between them.

    Kept a plain function so the geometry can be tested without a rendered
    widget, a mouse event or a dialog.
    """
    if len(text_specs) < 2:
        return None                     # one tick: which end is ambiguous
    centre = ((lambda rect: rect.center().x()) if horizontal
              else (lambda rect: rect.center().y()))
    ordered = sorted(text_specs, key=lambda spec: centre(spec[0]))
    first, last = ordered[0], ordered[-1]

    for spec, at_start in ((first, True), (last, False)):
        if spec[0].contains(pos):
            if horizontal:
                return "min" if at_start else "max"
            # screen y grows downwards, so the topmost label is the largest
            return "max" if at_start else "min"
    return None


class EditableAxis(pg.AxisItem):
    """An axis whose first and last tick labels can be double-clicked.

    The LabVIEW panels let you double-click either end tick of a graph and
    type a new limit; anything invalid reverted to what was there. This is
    that, and it is the only way to set an exact limit with the mouse - the
    drag tools always land somewhere approximate.

    Out-of-order values are refused (a minimum cannot sit above the
    maximum), but limits *beyond the data* are allowed on purpose: leaving
    headroom around a signal is a normal thing to want, and clamping to the
    data would make it impossible.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._text_specs: list = []

    # pyqtgraph computes the tick-label rectangles inside paint and throws
    # them away; catching them here is what makes hit-testing the real
    # labels possible, rather than guessing from a fraction of the width.
    def drawPicture(self, painter, axisSpec, tickSpecs, textSpecs) -> None:
        self._text_specs = list(textSpecs)
        super().drawPicture(painter, axisSpec, tickSpecs, textSpecs)

    @property
    def horizontal(self) -> bool:
        return self.orientation in ("bottom", "top")

    def current_limits(self) -> tuple[float, float] | None:
        """The axis range in the units shown, undoing log mode."""
        view = self.linkedView()
        if view is None:
            return None
        low, high = view.viewRange()[0 if self.horizontal else 1]
        if self.logMode:
            # pyqtgraph holds a log axis's range as log10, so a plot showing
            # 100 Hz reports 2.0. Everything the user sees or types is the
            # real number; the conversion belongs here and nowhere else.
            return 10.0 ** low, 10.0 ** high
        return low, high

    def set_limit(self, end: str, value: float) -> bool:
        """Move one limit. Returns False - changing nothing - if invalid."""
        limits = self.current_limits()
        if limits is None or end not in ("min", "max"):
            return False
        low, high = limits
        if not math.isfinite(value):
            return False
        if self.logMode and value <= 0:
            return False                # log10 of zero or less does not exist
        if (value >= high if end == "min" else value <= low):
            return False                # would invert or collapse the axis

        low, high = (value, high) if end == "min" else (low, value)
        if self.logMode:
            low, high = math.log10(low), math.log10(high)
        view = self.linkedView()
        if self.horizontal:
            view.setXRange(low, high, padding=0)
        else:
            view.setYRange(low, high, padding=0)
        return True

    def mouseDoubleClickEvent(self, event) -> None:
        end = limit_end_at(self._text_specs, event.pos(), self.horizontal)
        limits = self.current_limits()
        if end is None or limits is None:
            super().mouseDoubleClickEvent(event)
            return

        event.accept()
        current = limits[0 if end == "min" else 1]
        label = "Minimum" if end == "min" else "Maximum"
        axis = "X" if self.horizontal else "Y"
        # free text rather than a spin box: it accepts 1e-3 and does not
        # round a limit to however many decimals a spin box was given
        text, ok = QInputDialog.getText(
            self.getViewWidget(), f"{axis} axis {label.lower()}",
            f"{label} of the {axis} axis:", text=f"{current:g}")
        if not ok:
            return
        try:
            value = float(text)
        except ValueError:
            return                      # as LabVIEW did: keep what was there
        self.set_limit(end, value)


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
        # EditableAxis on both: double-clicking an end tick label sets
        # that limit exactly, which no drag tool can do
        self.plot_widget = pg.PlotWidget(
            viewBox=self.viewbox,
            axisItems={"bottom": EditableAxis("bottom"),
                       "left": EditableAxis("left")})
        self.plot_widget.setBackground(self._bg)
        for axis in ("bottom", "left"):
            self.plot_widget.getAxis(axis).setPen(self._fg)
            self.plot_widget.getAxis(axis).setTextPen(self._fg)
        # Light enough that the traces sit in front of it rather than
        # competing with it - the other half of drawing curves at 2px.
        self.plot_widget.showGrid(x=True, y=True, alpha=GRID_ALPHA)
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

    def addLegend(self, *args, **kwargs):
        """A legend that stays readable whatever is drawn behind it.

        pyqtgraph's default legend has no background, so its labels sit
        directly on the traces and vanish wherever a curve happens to run
        through them. Giving it the plot's own background colour - nearly
        opaque, with a faint border so it still reads as an overlay rather
        than a hole - keeps it legible on a dense plot without hiding much
        of the data.
        """
        kwargs.setdefault("offset", (-10, 10))
        legend = self.plot_widget.addLegend(*args, **kwargs)
        backing = QColor(self._bg)
        backing.setAlpha(LEGEND_OPACITY)
        border = QColor(self._fg)
        border.setAlpha(LEGEND_BORDER_ALPHA)
        legend.setBrush(pg.mkBrush(backing))
        legend.setPen(pg.mkPen(border, width=1))
        legend.setLabelTextColor(self._fg)
        return legend

    # -- behave like the PlotWidget we wrap ---------------------------------
    def __getattr__(self, name: str):
        # only reached for attributes this class does not define; guard the
        # bootstrap case where self.plot is not assigned yet
        try:
            plot = self.__dict__["plot_widget"]
        except KeyError:
            raise AttributeError(name) from None
        return getattr(plot, name)
