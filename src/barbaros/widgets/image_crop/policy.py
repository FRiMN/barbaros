from abc import ABC, abstractmethod

from PySide6.QtCore import QRect, QSize


class CropPolicy(ABC):
    """Base class for crop constraint rules"""

    @abstractmethod
    def apply(self, rect: QRect, image_size: QSize) -> QRect:
        pass


class BoundaryPolicy(CropPolicy):
    """Policy: forbids going outside the image boundaries"""

    def apply(self, rect: QRect, image_size: QSize) -> QRect:
        return rect.intersected(QRect(0, 0, image_size.width(), image_size.height()))


class MinSizePolicy(CropPolicy):
    """Policy: minimum area size (50x50 by default)"""

    def __init__(self, min_w: int = 50, min_h: int = 50):
        self.min_w = min_w
        self.min_h = min_h

    def apply(self, rect: QRect, image_size: QSize) -> QRect:
        rect = rect.normalized()
        max_w = image_size.width()
        max_h = image_size.height()

        if rect.width() < self.min_w:
            extra = self.min_w - rect.width()
            new_right = min(max_w, rect.right() + extra)
            new_left = max(0, new_right - self.min_w)
            rect = QRect(new_left, rect.top(), new_right - new_left, rect.height())

        if rect.height() < self.min_h:
            extra = self.min_h - rect.height()
            new_bottom = min(max_h, rect.bottom() + extra)
            new_top = max(0, new_bottom - self.min_h)
            rect = QRect(rect.left(), new_top, rect.width(), new_bottom - new_top)

        return rect
