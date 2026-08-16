"""A layout that wraps its widgets onto extra rows instead of demanding width.

Qt ships no flow layout, so this is the well-known ``QLayout`` subclass from
its own examples, trimmed to what SPWB needs.

**Why it matters here.** A ``QHBoxLayout``'s minimum width is the sum of its
children, and a child's minimum propagates all the way up to the window. One
row of controls that happens to be 1250 px wide therefore makes the whole
window refuse to be narrower than that, whatever the screen. The Time
Processing window had reached a 2052 px minimum this way - wider than a
1920-pixel display.

:meth:`FlowLayout.minimumSize` returns the *largest* child instead of the
sum, because a row that can wrap only ever needs to fit its widest single
item. That one difference is what lets the window shrink; the wrapping is
what keeps every control reachable while it does.

Use it where a ``QHBoxLayout`` of controls would otherwise set the floor::

    row = FlowLayout()
    row.addWidget(apply_button)
    row.addWidget(reset_button)

There is no ``addStretch``: a flow layout packs from the left and the spare
room is simply the gap after the last item on each line.
"""
from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy, QWidget

__all__ = ["FlowLayout"]

#: gap between items, horizontally and vertically
DEFAULT_SPACING = 6


class FlowLayout(QLayout):
    """Lay widgets out left to right, wrapping when the row runs out."""

    def __init__(self, parent: QWidget | None = None, *,
                 margin: int = 0, spacing: int = DEFAULT_SPACING) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(QMargins(margin, margin, margin, margin))

    # -- the QLayout contract ----------------------------------------------
    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:
        """Yes: the height depends on how many rows the width forces."""
        return True

    def heightForWidth(self, width: int) -> int:
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        """One row, as a QHBoxLayout would want - the preferred shape."""
        size = QSize(0, 0)
        for item in self._items:
            hint = item.sizeHint()
            size.setWidth(size.width() + hint.width() + self._spacing)
            size.setHeight(max(size.height(), hint.height()))
        return size + self._margins()

    def minimumSize(self) -> QSize:
        """The widest single item, **not** the sum of them.

        This is the whole point: a row that can wrap never needs more width
        than its largest child, so the window is free to be narrower than
        the controls laid end to end.
        """
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size + self._margins()

    # -- the actual packing -------------------------------------------------
    def _margins(self) -> QSize:
        margins = self.contentsMargins()
        return QSize(margins.left() + margins.right(),
                     margins.top() + margins.bottom())

    def _layout(self, rect: QRect, *, apply: bool) -> int:
        """Place the items; return the height needed. Returns without
        moving anything when ``apply`` is false, which is how
        ``heightForWidth`` asks a hypothetical question."""
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(),
                             -margins.right(), -margins.bottom())
        x, y = area.x(), area.y()
        row_height = 0

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if row_height and next_x - self._spacing > area.right() + 1:
                x = area.x()                       # wrap to the next row
                y = y + row_height + self._spacing
                next_x = x + hint.width() + self._spacing
                row_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            row_height = max(row_height, hint.height())

        return y + row_height - rect.y() + margins.bottom()


def flow_row(*widgets: QWidget, margin: int = 0,
             spacing: int = DEFAULT_SPACING) -> FlowLayout:
    """A :class:`FlowLayout` holding ``widgets``, in order."""
    layout = FlowLayout(margin=margin, spacing=spacing)
    for widget in widgets:
        widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(widget)
    return layout
