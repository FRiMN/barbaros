from abc import ABC, abstractmethod

from PySide6.QtCore import QRect, QSize


class CropPolicy(ABC):
    """Base class for crop constraint rules"""

    @abstractmethod
    def apply(self, rect: QRect, image_size: QSize) -> QRect:
        pass


class BoundaryPolicy(CropPolicy):
    """Policy: forbids going outside the image boundaries.

    The rect is clipped, so the selection may shrink at an edge. That is what
    resizing needs; for panning use PanBoundaryPolicy.
    """

    def apply(self, rect: QRect, image_size: QSize) -> QRect:
        return rect.intersected(QRect(0, 0, image_size.width(), image_size.height()))


class PanBoundaryPolicy(CropPolicy):
    """Policy: keeps a moved selection inside the image by translating it.

    Unlike BoundaryPolicy, the size is never changed: clipping a moved rect
    silently shrinks the selection when the user drags it against an edge.
    """

    def apply(self, rect: QRect, image_size: QSize) -> QRect:
        max_x = max(0, image_size.width() - rect.width())
        max_y = max(0, image_size.height() - rect.height())
        x = max(0, min(rect.x(), max_x))
        y = max(0, min(rect.y(), max_y))
        return QRect(x, y, rect.width(), rect.height())


class MinSizePolicy(CropPolicy):
    """Policy: minimum area size (50x50 by default).

    QRect width/height are right-left+1, so the right/bottom bound is
    image_size-1 and the size after moving the left/top edge is
    new_right-new_left+1. Without this the result would be one pixel short of
    the minimum at the left/top edge.
    """

    def __init__(self, min_w: int = 50, min_h: int = 50):
        self.min_w = min_w
        self.min_h = min_h

    def apply(self, rect: QRect, image_size: QSize) -> QRect:
        rect = rect.normalized()
        max_w = image_size.width()
        max_h = image_size.height()

        if rect.width() < self.min_w:
            extra = self.min_w - rect.width()
            new_right = min(max_w - 1, rect.right() + extra)
            new_left = max(0, new_right - self.min_w + 1)
            rect = QRect(new_left, rect.top(), new_right - new_left + 1, rect.height())

        if rect.height() < self.min_h:
            extra = self.min_h - rect.height()
            new_bottom = min(max_h - 1, rect.bottom() + extra)
            new_top = max(0, new_bottom - self.min_h + 1)
            rect = QRect(rect.left(), new_top, rect.width(), new_bottom - new_top + 1)

        return rect
