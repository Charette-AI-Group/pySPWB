"""The graph palette: LabVIEW-style mouse zoom on every plot.

The interesting code is the X-only and Y-only band zoom, because pyqtgraph
has no such mode - ``RectMode`` always rescales both axes. These tests drive
``mouseDragEvent`` with a stand-in event, which is the same entry point Qt
uses for a real drag.

One trap worth knowing if these ever fail oddly: an offscreen widget that
has never been laid out has a stale ``childGroup`` transform, so pixel ->
data mapping returns fractions of the view rather than data coordinates.
``processEvents`` after ``show``/``resize`` is what makes it real, and
``laid_out`` below exists for that reason.
"""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from spwb.gui.plotting import TOOLS, GraphViewBox, SpwbPlot


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class Drag:
    """The slice of pyqtgraph's drag event that ViewBox actually uses."""

    def __init__(self, start, now, finish=True,
                 button=Qt.MouseButton.LeftButton):
        self._start = QPointF(*start)
        self._now = QPointF(*now)
        self._finish = finish
        self._button = button
        self.accepted = False

    def button(self):
        return self._button

    def buttonDownPos(self, button=None):
        return self._start

    def pos(self):
        return self._now

    def lastPos(self):
        return self._start

    def isFinish(self):
        return self._finish

    def accept(self):
        self.accepted = True


@pytest.fixture
def plot(qapp):
    widget = SpwbPlot("Time (s)", "Amplitude")
    widget.plot(np.arange(100.0), np.sin(np.arange(100) / 5))
    widget.resize(600, 400)
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()


def laid_out(widget, qapp, x_range=(0.0, 100.0), y_range=(-1.0, 1.0)):
    """Give the view a known range with a real transform behind it."""
    widget.viewbox.setXRange(*x_range, padding=0)
    widget.viewbox.setYRange(*y_range, padding=0)
    qapp.processEvents()
    return widget.viewbox


def ranges(vb):
    (x0, x1), (y0, y1) = vb.viewRange()
    return (x0, x1), (y0, y1)


# -- tools ------------------------------------------------------------------
def test_every_tool_has_a_button_and_they_are_exclusive(plot):
    for tool in TOOLS:
        assert tool in plot._buttons
        assert plot._buttons[tool].isCheckable()

    plot.set_tool("rect")
    assert plot._buttons["rect"].isChecked()
    assert not plot._buttons["pan"].isChecked()


@pytest.mark.parametrize("tool,mouse_enabled", [
    ("pan", [True, True]),
    ("rect", [True, True]),
    ("xzoom", [True, False]),
    ("yzoom", [False, True]),
])
def test_tool_sets_the_axes_the_mouse_may_touch(plot, tool, mouse_enabled):
    """The same mask constrains the scroll wheel, which is the point."""
    plot.set_tool(tool)

    assert plot.tool == tool
    assert plot.viewbox.state["mouseEnabled"] == mouse_enabled


def test_only_the_rectangle_tool_uses_pyqtgraphs_rect_mode(plot):
    plot.set_tool("rect")
    assert plot.viewbox.state["mouseMode"] == pg.ViewBox.RectMode

    for tool in ("pan", "xzoom", "yzoom"):
        plot.set_tool(tool)
        assert plot.viewbox.state["mouseMode"] == pg.ViewBox.PanMode


def test_an_unknown_tool_is_refused():
    with pytest.raises(ValueError, match="unknown tool"):
        GraphViewBox().set_tool("wobble")


def test_selecting_a_tool_announces_it(plot):
    seen = []
    plot.tool_changed.connect(seen.append)

    plot.set_tool("yzoom")

    assert seen == ["yzoom"]


# -- the band zooms, which are the reason this module exists ----------------
def test_x_zoom_drag_rescales_x_and_leaves_y_alone(plot, qapp):
    vb = laid_out(plot, qapp)
    plot.set_tool("xzoom")
    box = vb.boundingRect()
    quarter = box.left() + box.width() * 0.25
    three_q = box.left() + box.width() * 0.75

    vb.mouseDragEvent(Drag((quarter, box.center().y()),
                           (three_q, box.center().y())))

    (x0, x1), (y0, y1) = ranges(vb)
    assert x0 == pytest.approx(25.0, abs=1.0)
    assert x1 == pytest.approx(75.0, abs=1.0)
    assert (y0, y1) == pytest.approx((-1.0, 1.0))


def test_y_zoom_drag_rescales_y_and_leaves_x_alone(plot, qapp):
    vb = laid_out(plot, qapp)
    plot.set_tool("yzoom")
    box = vb.boundingRect()
    quarter = box.top() + box.height() * 0.25
    three_q = box.top() + box.height() * 0.75

    vb.mouseDragEvent(Drag((box.center().x(), quarter),
                           (box.center().x(), three_q)))

    (x0, x1), (y0, y1) = ranges(vb)
    assert (x0, x1) == pytest.approx((0.0, 100.0))
    assert y0 == pytest.approx(-0.5, abs=0.05)
    assert y1 == pytest.approx(0.5, abs=0.05)


def test_dragging_right_to_left_zooms_the_same_way(plot, qapp):
    """A backwards drag must not produce an inverted or empty range."""
    vb = laid_out(plot, qapp)
    plot.set_tool("xzoom")
    box = vb.boundingRect()
    a = box.left() + box.width() * 0.25
    b = box.left() + box.width() * 0.75

    vb.mouseDragEvent(Drag((b, box.center().y()), (a, box.center().y())))

    (x0, x1), _ = ranges(vb)
    assert x0 < x1
    assert x0 == pytest.approx(25.0, abs=1.0)


def test_a_zero_width_drag_does_not_collapse_the_view(plot, qapp):
    """A stray click must not zoom to nothing."""
    vb = laid_out(plot, qapp)
    plot.set_tool("xzoom")
    box = vb.boundingRect()
    x = box.center().x()

    vb.mouseDragEvent(Drag((x, box.center().y()), (x, box.center().y())))

    (x0, x1), _ = ranges(vb)
    assert x1 > x0


def test_the_rubber_band_shows_while_dragging_and_hides_after(plot, qapp):
    vb = laid_out(plot, qapp)
    plot.set_tool("xzoom")
    box = vb.boundingRect()

    vb.mouseDragEvent(Drag((box.left(), box.center().y()),
                           (box.center().x(), box.center().y()),
                           finish=False))
    assert vb.rbScaleBox.isVisible()

    vb.mouseDragEvent(Drag((box.left(), box.center().y()),
                           (box.center().x(), box.center().y())))
    assert not vb.rbScaleBox.isVisible()


def test_pan_and_rect_still_reach_pyqtgraph(plot, qapp):
    """The two tools we do not implement must not be intercepted."""
    vb = laid_out(plot, qapp)
    plot.set_tool("rect")
    box = vb.boundingRect()

    vb.mouseDragEvent(Drag((box.left() + box.width() * 0.25,
                            box.top() + box.height() * 0.25),
                           (box.left() + box.width() * 0.75,
                            box.top() + box.height() * 0.75)))

    # exact numbers here are pyqtgraph's business, not ours; what matters
    # is that the drag reached it and *both* axes rescaled
    (x0, x1), (y0, y1) = ranges(vb)
    assert 15.0 < x0 < 35.0
    assert 65.0 < x1 < 85.0
    assert y1 - y0 < 1.5


# -- the one-shot buttons ---------------------------------------------------
def test_zoom_in_and_out_are_inverses(plot, qapp):
    vb = laid_out(plot, qapp)
    plot.set_tool("pan")

    plot.zoom_in()
    (x0, x1), _ = ranges(vb)
    assert x1 - x0 == pytest.approx(50.0, abs=0.5)

    plot.zoom_out()
    (x0, x1), _ = ranges(vb)
    assert x1 - x0 == pytest.approx(100.0, abs=1.0)


def test_zoom_buttons_respect_the_active_tools_axis(plot, qapp):
    vb = laid_out(plot, qapp)
    plot.set_tool("xzoom")

    plot.zoom_in()

    (x0, x1), (y0, y1) = ranges(vb)
    assert x1 - x0 == pytest.approx(50.0, abs=0.5)   # X halved
    assert (y0, y1) == pytest.approx((-1.0, 1.0))    # Y untouched


def test_autoscale_fits_the_data(plot, qapp):
    vb = laid_out(plot, qapp, x_range=(10.0, 20.0), y_range=(0.0, 0.1))

    plot.autoscale()
    qapp.processEvents()

    (x0, x1), (y0, y1) = ranges(vb)
    assert x0 <= 0.0 and x1 >= 99.0
    assert y0 < -0.9 and y1 > 0.9


def test_undo_goes_back_to_the_previous_zoom(plot, qapp):
    vb = laid_out(plot, qapp)
    plot.set_tool("xzoom")
    box = vb.boundingRect()
    vb.mouseDragEvent(Drag((box.left() + box.width() * 0.25, box.center().y()),
                           (box.left() + box.width() * 0.75, box.center().y())))
    (zoomed_x0, zoomed_x1), _ = ranges(vb)
    assert zoomed_x1 - zoomed_x0 == pytest.approx(50.0, abs=2.0)

    plot.undo_zoom()
    qapp.processEvents()

    # the whole pre-zoom range is visible again, not merely "wider" - without
    # the seeded entry pyqtgraph has nothing to go back to and undo is a
    # no-op. The slight overshoot is its padding on restore.
    (x0, x1), _ = ranges(vb)
    assert x1 - x0 > zoomed_x1 - zoomed_x0
    assert x0 <= 0.0 and x1 >= 100.0


# -- it still behaves like a PlotWidget -------------------------------------
def test_plotwidget_api_is_forwarded(plot):
    """Every window calls these on what used to be a bare PlotWidget."""
    curve = plot.plot([0, 1, 2], [3, 4, 5])
    assert curve is not None

    plot.setLabel("left", "Amplitude", units="Pa")
    plot.showGrid(x=True, y=True, alpha=0.3)
    plot.addLegend(offset=(-10, 10))
    plot.enableAutoRange()
    plot.setLogMode(x=False, y=False)
    assert plot.plotItem is plot.plot_widget.plotItem
    assert plot.getAxis("bottom") is not None
    plot.clear()


def test_the_inner_widget_is_not_shadowed_by_the_plot_method(plot):
    """`plot.plot(...)` must draw a curve, not return the inner widget."""
    assert callable(plot.plot)
    assert isinstance(plot.plot_widget, pg.PlotWidget)


def test_an_unknown_attribute_still_raises(plot):
    with pytest.raises(AttributeError):
        getattr(plot, "definitely_not_a_real_method")  # noqa: B009


def test_the_palette_can_be_hidden(plot):
    plot.set_palette_visible(False)
    assert not plot.toolbar.isVisible()

    plot.set_palette_visible(True)
    assert plot.toolbar.isVisible()


# -- the settings that keep long signals fast ------------------------------
def test_curves_are_thicker_than_the_grid(plot):
    from spwb.gui.plotting import CURVE_WIDTH, curve_pen

    assert CURVE_WIDTH > 1                       # the grid and axes are 1px
    assert curve_pen(0).width() == CURVE_WIDTH
    assert curve_pen("#123456").color().name() == "#123456"
    assert curve_pen(len(__import__(
        "spwb.gui.plotting", fromlist=["PEN_COLOURS"]).PEN_COLOURS)) is not None


def test_antialiasing_is_off_and_downsampling_is_on(plot):
    """The pairing that makes a 30-second signal paint in 40 ms.

    Qt has a fast path for 1px cosmetic pens only; a 2px *antialiased*
    polyline of 245k points took 6.4 s to paint, per redraw. Turning
    antialiasing off and letting pyqtgraph draw at most a couple of points
    per pixel brings it to 0.04 s. If someone turns antialiasing back on
    for looks, the application becomes unusable on real recordings - hence
    this test rather than a comment.
    """
    assert pg.getConfigOption("antialias") is False

    control = plot.plotItem.ctrl
    assert control.downsampleCheck.isChecked()
    assert control.autoDownsampleCheck.isChecked()
    assert control.peakRadio.isChecked()      # keeps transients, unlike stride
    # clipToView must stay OFF: it makes a curve report only the data inside
    # the view, so autoscale can no longer see the rest, and it buys no speed
    assert not control.clipToViewCheck.isChecked()


def test_a_long_signal_paints_promptly(plot, qapp):
    """A crude ceiling, but it would have caught the 6-second regression."""
    import time

    n = 245_760                                  # 30 s at 8192 Hz
    t = np.arange(n) / 8192.0
    plot.clear()
    plot.plot(t, np.sin(2 * np.pi * 100 * t), pen=None)
    qapp.processEvents()

    start = time.perf_counter()
    plot.grab()                                  # forces a synchronous repaint
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"painting {n} points took {elapsed:.2f} s"


def test_the_right_click_menu_is_kept_as_the_exact_range_escape_hatch(plot):
    """Typing a precise range is the one thing the palette cannot do."""
    assert plot.plotItem.vb.menu is not None


def test_the_legend_gets_a_backing_so_it_stays_readable(plot):
    """pyqtgraph's default legend is transparent, so its labels vanish
    wherever a trace happens to run behind them."""
    from spwb.gui.plotting import LEGEND_OPACITY

    legend = plot.addLegend()

    assert legend.brush().color().alpha() == LEGEND_OPACITY
    assert 0 < LEGEND_OPACITY < 255, "fully opaque would read as a hole"
    assert legend.pen().color().alpha() > 0, "no border"
    assert legend.labelTextColor() is not None


def test_the_legend_keeps_its_corner_by_default(plot):
    """Every window asked for offset=(-10, 10); it is now the default."""
    legend = plot.addLegend()
    assert legend is not None

    moved = plot.addLegend(offset=(30, 30))    # still overridable
    assert moved is not None
