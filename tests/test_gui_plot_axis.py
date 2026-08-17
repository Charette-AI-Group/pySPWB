"""Double-clicking an end tick label to type an exact axis limit.

The LabVIEW panels let you double-click the first or last tick of a graph
and enter a new limit, reverting if the number made no sense. This is that
behaviour, and it is the only way to set an exact limit with the mouse -
every drag tool lands somewhere approximate.

Deliberate decision recorded here: limits **beyond the data** are allowed,
because leaving headroom around a signal is a normal thing to want. Only
values that would invert or collapse the axis are refused.
"""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

from spwb.gui.plotting import EditableAxis, SpwbPlot, limit_end_at


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def plot(qapp):
    p = SpwbPlot("Frequency (Hz)", "Amplitude")
    p.resize(800, 450)
    p.plot(np.arange(1000, dtype=float), np.sin(np.arange(1000) / 50.0))
    p.viewbox.setXRange(0.0, 1000.0, padding=0)
    p.viewbox.setYRange(-1.0, 1.0, padding=0)
    yield p
    p.deleteLater()


def specs(*rects):
    """Tick-label draw specs, as pyqtgraph builds them: (rect, flags, text)."""
    return [(rect, 0, str(i)) for i, rect in enumerate(rects)]


# -- the geometry, without a rendered widget --------------------------------
def test_first_and_last_label_on_a_horizontal_axis():
    left, middle, right = (QRectF(0, 0, 20, 10), QRectF(100, 0, 20, 10),
                           QRectF(200, 0, 20, 10))
    ticks = specs(left, middle, right)

    assert limit_end_at(ticks, QPointF(10, 5), horizontal=True) == "min"
    assert limit_end_at(ticks, QPointF(210, 5), horizontal=True) == "max"
    assert limit_end_at(ticks, QPointF(110, 5), horizontal=True) is None


def test_a_vertical_axis_is_upside_down():
    """Screen y grows downwards, so the topmost label is the largest value."""
    top, middle, bottom = (QRectF(0, 0, 20, 10), QRectF(0, 100, 20, 10),
                           QRectF(0, 200, 20, 10))
    ticks = specs(top, middle, bottom)

    assert limit_end_at(ticks, QPointF(5, 5), horizontal=False) == "max"
    assert limit_end_at(ticks, QPointF(5, 205), horizontal=False) == "min"
    assert limit_end_at(ticks, QPointF(5, 105), horizontal=False) is None


def test_a_click_away_from_every_label_is_not_a_limit():
    ticks = specs(QRectF(0, 0, 20, 10), QRectF(200, 0, 20, 10))

    assert limit_end_at(ticks, QPointF(500, 5), horizontal=True) is None


def test_one_tick_is_ambiguous_and_refused():
    """With a single label there is no first *and* last to tell apart."""
    ticks = specs(QRectF(0, 0, 20, 10))

    assert limit_end_at(ticks, QPointF(10, 5), horizontal=True) is None
    assert limit_end_at([], QPointF(10, 5), horizontal=True) is None


# -- the plot the windows actually use --------------------------------------
def test_every_plot_gets_editable_axes(plot):
    for name in ("bottom", "left"):
        assert isinstance(plot.plot_widget.getAxis(name), EditableAxis)


def test_setting_a_limit_moves_that_edge_only(plot):
    bottom = plot.plot_widget.getAxis("bottom")

    assert bottom.set_limit("min", 200.0)
    assert bottom.current_limits() == pytest.approx((200.0, 1000.0))
    assert bottom.set_limit("max", 800.0)
    assert bottom.current_limits() == pytest.approx((200.0, 800.0))


def test_limits_beyond_the_data_are_allowed(plot):
    """The decision this feature was built with: headroom is legitimate."""
    left = plot.plot_widget.getAxis("left")

    assert left.set_limit("min", -50.0)
    assert left.set_limit("max", 50.0)
    assert left.current_limits() == pytest.approx((-50.0, 50.0))


@pytest.mark.parametrize("end,value", [("min", 1000.0),   # equal to the max
                                       ("min", 2000.0),   # above the max
                                       ("max", 0.0),      # equal to the min
                                       ("max", -5.0),     # below the min
                                       ("min", float("nan")),
                                       ("min", float("inf"))])
def test_a_value_that_would_break_the_axis_changes_nothing(plot, end, value):
    bottom = plot.plot_widget.getAxis("bottom")
    before = bottom.current_limits()

    assert bottom.set_limit(end, value) is False
    assert bottom.current_limits() == pytest.approx(before)


def test_an_unknown_end_is_refused(plot):
    bottom = plot.plot_widget.getAxis("bottom")

    assert bottom.set_limit("middle", 500.0) is False


# -- log axes ---------------------------------------------------------------
def test_a_log_axis_shows_and_takes_real_numbers(plot):
    """pyqtgraph stores a log range as log10; the user never sees that."""
    plot.setLogMode(x=True, y=False)
    plot.viewbox.setXRange(0.0, 4.0, padding=0)          # 1 Hz .. 10 kHz
    bottom = plot.plot_widget.getAxis("bottom")

    assert bottom.current_limits() == pytest.approx((1.0, 10000.0))

    assert bottom.set_limit("min", 100.0)

    assert bottom.current_limits() == pytest.approx((100.0, 10000.0))
    # the stored range is the logarithm, which is what would go wrong if the
    # conversion were missing: the view would jump to 10^100
    assert plot.viewbox.viewRange()[0] == pytest.approx([2.0, 4.0])


@pytest.mark.parametrize("value", [0.0, -1.0])
def test_a_log_axis_refuses_zero_and_below(plot, value):
    plot.setLogMode(x=True, y=False)
    plot.viewbox.setXRange(0.0, 4.0, padding=0)
    bottom = plot.plot_widget.getAxis("bottom")

    assert bottom.set_limit("min", value) is False
    assert bottom.current_limits() == pytest.approx((1.0, 10000.0))


# -- against real rendered labels -------------------------------------------
def test_the_real_tick_labels_can_be_hit(plot, qapp):
    """The rectangles only exist once the axis has painted, so paint it."""
    plot.grab()                        # a real paint, as the manuals' shots do
    qapp.processEvents()

    for name, first_is in (("bottom", "min"), ("left", "max")):
        axis = plot.plot_widget.getAxis(name)
        ticks = axis._text_specs
        assert len(ticks) >= 2, f"{name} axis drew no tick labels"

        key = ((lambda s: s[0].center().x()) if axis.horizontal
               else (lambda s: s[0].center().y()))
        ordered = sorted(ticks, key=key)
        last_is = "max" if first_is == "min" else "min"

        assert limit_end_at(ticks, ordered[0][0].center(),
                            axis.horizontal) == first_is
        assert limit_end_at(ticks, ordered[-1][0].center(),
                            axis.horizontal) == last_is
        middle = ordered[len(ordered) // 2]
        if middle is not ordered[0] and middle is not ordered[-1]:
            assert limit_end_at(ticks, middle[0].center(),
                                axis.horizontal) is None


def test_setting_a_limit_turns_off_autoscale_and_fit_restores_it(plot):
    """Otherwise the next redraw would silently undo what was just typed."""
    bottom = plot.plot_widget.getAxis("bottom")
    bottom.set_limit("min", 300.0)

    # pyqtgraph reports this as False when off and as the fraction of the
    # data to show - 1.0 - when on, so compare truthiness, not identity
    assert not plot.viewbox.autoRangeEnabled()[0]

    plot.autoscale()

    assert plot.viewbox.autoRangeEnabled()[0]
