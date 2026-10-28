from abc import ABC, abstractmethod
from enum import IntEnum

from PySide6.QtCore import QPoint, QRect


class CropStrategy(ABC):
    """Базовый класс для стратегий изменения выделения при drag-and-drop.

    Выделение хранится в пикселях изображения. На нажатии стратегия запоминает
    точку нажатия (drag_start) и выделение в этот момент (rect_on_press), а
    on_mouse_move получает сдвиг курсора относительно точки нажатия.

    Абсолютная позиция курсора намеренно не используется: ручки невидимы и
    занимают зону в десятки пикселей, поэтому «ручка = курсор» приводила бы к
    скачку выделения при нажатии внутри зоны. Расчёт всегда идёт от
    rect_on_press, поэтому клампы одного хода не накапливаются между ходами.
    """

    def __init__(self):
        self.drag_start = QPoint()
        self.rect_on_press = QRect()

    def on_mouse_press(self, pos: QPoint, rect: QRect):
        """Запоминает точку нажатия и выделение на момент нажатия."""
        self.drag_start = pos
        self.rect_on_press = rect

    @abstractmethod
    def on_mouse_move(self, delta: QPoint) -> QRect:
        """
        Выделение после сдвига курсора на delta от точки нажатия.

        delta - сдвиг курсора в пикселях изображения
        """
        pass


class HandlePos(IntEnum):
    """Кнопка/ручка выделения в виджете обрезки — ключ диспетчеризации к
    соответствующей CropStrategy."""

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
    """Изменение размера за угол: угол-якорь неподвижен, противоположный угол
    смещается на сдвиг мыши (а не в позицию курсора).
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
    """Изменение размера за сторону: противоположная сторона неподвижна,
    сторона под курсором смещается на сдвиг мыши по своей оси.
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
    """Перемещение выделения без изменения размера: весь прямоугольник
    смещается на сдвиг мыши.
    """

    def on_mouse_move(self, delta: QPoint) -> QRect:
        return self.rect_on_press.translated(delta)


class CreateStrategy(CropStrategy):
    """Создание нового выделения: прямоугольник строится от точки нажатия до
    текущего положения курсора, поэтому здесь сдвиг прибавляется к точке
    нажатия.
    """

    def on_mouse_move(self, delta: QPoint) -> QRect:
        return QRect(self.drag_start, self.drag_start + delta)
