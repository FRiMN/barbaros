import sys
from abc import ABC, abstractmethod
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QRect, QPoint, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap


# --- ПОЛИТИКИ (POLICIES) ---

class CropPolicy(ABC):
    """Базовый класс для правил ограничения обрезки"""
    @abstractmethod
    def apply(self, rect: QRect, image_size: QSize) -> QRect:
        pass

class BoundaryPolicy(CropPolicy):
    """Политика: запрещает выходить за границы изображения"""
    def apply(self, rect: QRect, image_size: QSize) -> QRect:
        # Обрезаем прямоугольник по границам изображения
        return rect.intersected(QRect(0, 0, image_size.width(), image_size.height()))

class MinSizePolicy(CropPolicy):
    """Политика: минимальный размер области 50x50"""
    def __init__(self, min_w=50, min_h=50):
        self.min_w = min_w
        self.min_h = min_h

    def apply(self, rect: QRect, image_size: QSize) -> QRect:
        if rect.width() < self.min_w or rect.height() < self.min_h:
            # Тут логика расширения прямоугольника до минимума
            # (Для простоты просто возвращаем как есть, если слишком мало)
            pass
        return rect


# --- СТРАТЕГИИ ТРАНСФОРМАЦИИ ---

class CropStrategy(ABC):
    """Абстрактный базовый класс для стратегии изменения выделения"""

    def on_mouse_press(self, pos: QPoint, rect: QRect):
        """Метод для подготовки состояния перед началом drag-and-drop."""
        pass

    @abstractmethod
    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        pass


class CornerStrategy(CropStrategy):
    def __init__(self, anchor_type: str):
        self.anchor = anchor_type

    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        if self.anchor == 'tl': return QRect(pos, rect.bottomRight())
        if self.anchor == 'tr': return QRect(
            rect.topLeft().x(), pos.y(),
            pos.x() - rect.topLeft().x(), rect.bottom() - pos.y()
        )
        if self.anchor == 'bl': return QRect(
            pos.x(), rect.topLeft().y(),
            rect.right() - pos.x(), pos.y() - rect.topLeft().y()
        )
        if self.anchor == 'br': return QRect(rect.topLeft(), pos)
        return rect


class SideStrategy(CropStrategy):
    def __init__(self, side):
        self.side = side

    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        if self.side == 'top':    return QRect(rect.left(), pos.y(), rect.width(), rect.bottom() - pos.y())
        if self.side == 'bottom':  return QRect(rect.left(), rect.top(), rect.width(), pos.y() - rect.top())
        if self.side == 'left':   return QRect(pos.x(), rect.top(), rect.right() - pos.x(), rect.height())
        if self.side == 'right':  return QRect(rect.left(), rect.top(), pos.x() - rect.left(), rect.height())
        return rect


class PanStrategy(CropStrategy):
    def __init__(self):
        self.drag_start = QPoint()
        self.rect_start = QPoint()

    def on_mouse_press(self, pos: QPoint, rect: QRect):
        self.drag_start = pos
        self.rect_start = rect.topLeft()

    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        delta = pos - self.drag_start
        new_tl = self.rect_start + delta
        new_br = rect.bottomRight() + delta
        new_rect = QRect(
            new_tl,
            new_br
        )
        assert rect.size() == new_rect.size()
        return new_rect


class CreateStrategy(CropStrategy):
    def __init__(self):
        self.begin = QPoint()

    def on_mouse_press(self, pos: QPoint, rect: QRect):
        self.begin = pos

    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        return QRect(self.begin, pos)


# --- ОСНОВНОЙ ВИДЖЕТ ---

class HandlePos:
    NONE = 0
    TOP_LEFT = 1
    TOP_RIGHT = 2
    BOTTOM_LEFT = 3
    BOTTOM_RIGHT = 4
    TOP_CENTER = 5
    BOTTOM_CENTER = 6
    LEFT_CENTER = 7
    RIGHT_CENTER = 8
    INSIDE = 9


class GimpStyleCropSelection(QWidget):
    def __init__(self, image_path):
        super().__init__()
        self.image = QPixmap(image_path)
        self.setFixedSize(self.image.size())

        self.selection_rect = QRect()
        self.handle_size = 8
        self.active_handle = HandlePos.NONE
        self.is_selecting = False

        self.strategies = {
            HandlePos.TOP_LEFT: CornerStrategy('tl'),
            HandlePos.TOP_RIGHT: CornerStrategy('tr'),
            HandlePos.BOTTOM_LEFT: CornerStrategy('bl'),
            HandlePos.BOTTOM_RIGHT: CornerStrategy('br'),
            HandlePos.TOP_CENTER: SideStrategy('top'),
            HandlePos.BOTTOM_CENTER: SideStrategy('bottom'),
            HandlePos.LEFT_CENTER: SideStrategy('left'),
            HandlePos.RIGHT_CENTER: SideStrategy('right'),
            HandlePos.INSIDE: PanStrategy(),
            HandlePos.NONE: CreateStrategy(),
        }

        self.handle_map = {
            HandlePos.TOP_LEFT: lambda r, s: QRect(r.topLeft().x() - s, r.topLeft().y() - s, 2 * s, 2 * s),
            HandlePos.TOP_RIGHT: lambda r, s: QRect(r.topRight().x() - s, r.topRight().y() - s, 2 * s, 2 * s),
            HandlePos.BOTTOM_LEFT: lambda r, s: QRect(r.bottomLeft().x() - s, r.bottomLeft().y() - s, 2 * s, 2 * s),
            HandlePos.BOTTOM_RIGHT: lambda r, s: QRect(r.bottomRight().x() - s, r.bottomRight().y() - s, 2 * s, 2 * s),
            HandlePos.TOP_CENTER: lambda r, s: QRect(r.center().x() - s, r.top() - s, 2 * s, 2 * s),
            HandlePos.BOTTOM_CENTER: lambda r, s: QRect(r.center().x() - s, r.bottom() - s, 2 * s, 2 * s),
            HandlePos.LEFT_CENTER: lambda r, s: QRect(r.left() - s, r.center().y() - s, 2 * s, 2 * s),
            HandlePos.RIGHT_CENTER: lambda r, s: QRect(r.right() - s, r.center().y() - s, 2 * s, 2 * s),
        }

        # Список активных политик
        self.policies = [
            BoundaryPolicy(),
            MinSizePolicy(50, 50),
        ]

    def get_handle_at(self, pos):
        if self.selection_rect.isNull(): return HandlePos.NONE

        s = self.handle_size // 2
        for h_id, func in self.handle_map.items():
            if func(self.selection_rect, s).contains(pos): return h_id

        if self.selection_rect.contains(pos): return HandlePos.INSIDE
        return HandlePos.NONE

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        self.active_handle = self.get_handle_at(pos)
        self.is_selecting = True

        # УНИФИЦИРОВАННЫЙ ВЫЗОВ:
        # Мы просто говорим стратегии: "Вот текущая ситуация, подготовься".
        # Если стратегии не нужно состояние (как CornerStrategy), она просто проигнорирует вызов.
        self.strategies[self.active_handle].on_mouse_press(pos, self.selection_rect)

        self.update()

    def mouseMoveEvent(self, event):
        if not self.is_selecting: return
        pos = event.position().toPoint()

        # 1. СТРАТЕГИЯ: рассчитывает "желаемый" результат
        strategy = self.strategies[self.active_handle]
        proposed_rect = strategy.on_mouse_move(self.selection_rect, pos).normalized()

        # 2. ПОЛИТИКИ: фильтруют и корректируют этот результат
        final_rect = proposed_rect
        # for policy in self.policies:
        #     final_rect = policy.apply(final_rect, self.image.size())

        self.selection_rect = final_rect
        self.update()

    def mouseReleaseEvent(self, event):
        self.is_selecting = False
        self.active_handle = HandlePos.NONE
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self.image)

        if not self.selection_rect.isNull():
            rect = self.selection_rect
            overlay_color = QColor(0, 0, 0, 100)
            painter.fillRect(0, 0, self.width(), rect.top(), overlay_color)
            painter.fillRect(0, rect.bottom(), self.width(), self.height() - rect.bottom(), overlay_color)
            painter.fillRect(0, rect.top(), rect.left(), rect.height(), overlay_color)
            painter.fillRect(rect.right(), rect.top(), self.width() - rect.right(), rect.height(), overlay_color)

            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)

            painter.setBrush(QBrush(QColor(255, 255, 255)))
            s = self.handle_size // 2
            for h_id, func in self.handle_map.items():
                painter.drawRect(func(rect, s))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GimpStyleCropSelection('/home/nik/Изображения/Снимок экрана_2026-10-10_14-35-11.png')
    window.show()
    sys.exit(app.exec())