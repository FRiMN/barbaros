from abc import ABC, abstractmethod
from enum import IntEnum

from PySide6.QtCore import QPoint, QRect


class CropStrategy(ABC):
    """Base class for selection-change strategies on drag-and-drop.

    The selection is stored in image pixels. On press the strategy records the
    press point (drag_start) and the selection at that moment (rect_on_press),
    while on_mouse_move receives the cursor delta relative to the press point.

    The absolute cursor position is deliberately not used: handles are invisible
    and occupy a zone of tens of pixels, so "handle = cursor" would make the
    selection jump when pressing inside the zone. The calculation always starts
    from rect_on_press, so clamps from one move do not accumulate between moves.
    """

    def __init__(self):
        self.drag_start = QPoint()
        self.rect_on_press = QRect()

    def on_mouse_press(self, pos: QPoint, rect: QRect):
        """Records the press point and the selection at the moment of press."""
        self.drag_start = pos
        self.rect_on_press = rect

    @abstractmethod
    def on_mouse_move(self, delta: QPoint) -> QRect:
        """
        The selection after the cursor has moved by delta from the press point.

        delta - cursor delta in image pixels
        """
        pass


class HandlePos(IntEnum):
    """Selection button/handle in the crop widget — the dispatch key to the
    corresponding CropStrategy."""

    NONE = 0    # outside
    TOP_LEFT = 1
    TOP_RIGHT = 2
    BOTTOM_LEFT = 3
    BOTTOM_RIGHT = 4
    TOP_CENTER = 5
    BOTTOM_CENTER = 6
    LEFT_CENTER = 7
    RIGHT_CENTER = 8
    INSIDE = 9


class CornerStrategy(CropStrategy):
    """Resizing by a corner: the anchor corner stays fixed, the opposite corner
    moves by the mouse delta (not to the cursor position).
    """

    valid_handle_pos = {
        HandlePos.TOP_LEFT,
        HandlePos.TOP_RIGHT,
        HandlePos.BOTTOM_LEFT,
        HandlePos.BOTTOM_RIGHT
    }

    def __init__(self, anchor: HandlePos):
        super().__init__()
        if anchor not in self.valid_handle_pos:
            raise ValueError(f"CornerStrategy requires a corner anchor ({self.valid_handle_pos}), got {anchor}")
        self.anchor = anchor

    def on_mouse_move(self, delta: QPoint) -> QRect:
        rect = self.rect_on_press
        dx, dy = delta.x(), delta.y()
        match self.anchor:
            case HandlePos.TOP_LEFT:
                return QRect(rect.topLeft() + QPoint(dx, dy), rect.bottomRight())
            case HandlePos.TOP_RIGHT:
                return QRect(
                    QPoint(rect.left(), rect.top() + dy),
                    QPoint(rect.right() + dx, rect.bottom()),
                )
            case HandlePos.BOTTOM_LEFT:
                return QRect(
                    QPoint(rect.left() + dx, rect.top()),
                    QPoint(rect.right(), rect.bottom() + dy),
                )
            case HandlePos.BOTTOM_RIGHT:
                return QRect(rect.topLeft(), rect.bottomRight() + QPoint(dx, dy))


class SideStrategy(CropStrategy):
    """Resizing by a side: the opposite side stays fixed, the side under the
    cursor moves by the mouse delta along its own axis.
    """

    valid_handle_pos = {
        HandlePos.TOP_CENTER,
        HandlePos.BOTTOM_CENTER,
        HandlePos.LEFT_CENTER,
        HandlePos.RIGHT_CENTER
    }

    def __init__(self, anchor: HandlePos):
        super().__init__()
        if anchor not in self.valid_handle_pos:
            raise ValueError(f"SideStrategy requires a side anchor ({self.valid_handle_pos}), got {anchor}")
        self.anchor = anchor

    def on_mouse_move(self, delta: QPoint) -> QRect:
        rect = self.rect_on_press
        dx, dy = delta.x(), delta.y()
        match self.anchor:
            case HandlePos.TOP_CENTER:
                return QRect(QPoint(rect.left(), rect.top() + dy), rect.bottomRight())
            case HandlePos.BOTTOM_CENTER:
                return QRect(rect.topLeft(), QPoint(rect.right(), rect.bottom() + dy))
            case HandlePos.LEFT_CENTER:
                return QRect(QPoint(rect.left() + dx, rect.top()), rect.bottomRight())
            case HandlePos.RIGHT_CENTER:
                return QRect(rect.topLeft(), QPoint(rect.right() + dx, rect.bottom()))


class PanStrategy(CropStrategy):
    """Moving the selection without resizing: the whole rectangle is shifted
    by the mouse delta.
    """

    def on_mouse_move(self, delta: QPoint) -> QRect:
        return self.rect_on_press.translated(delta)


class CreateStrategy(CropStrategy):
    """Creating a new selection: the rectangle is built from the press point to
    the current cursor position, so here the delta is added to the press point.
    """

    def on_mouse_move(self, delta: QPoint) -> QRect:
        return QRect(self.drag_start, self.drag_start + delta)
