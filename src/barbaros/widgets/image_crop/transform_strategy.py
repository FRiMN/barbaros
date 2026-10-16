from abc import ABC, abstractmethod

from PySide6.QtCore import QPoint, QRect


class CropStrategy(ABC):
    """Базовый класс для стратегий изменения выделения при drag-and-drop.

    Методы переопределяются в подклассах:
        on_mouse_press — вызывается в момент нажатия кнопки мыши;
        on_mouse_move — вызывается при каждом перемещении курсора и
            возвращает новое выделение.
    """

    def on_mouse_press(self, pos: QPoint, rect: QRect):
        """Метод для подготовки состояния перед началом drag-and-drop."""
        pass

    @abstractmethod
    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        """
        Метод для расчета трансформации rect при drag-and-drop.

        rect - выделение
        pos - позиция курсора
        """
        pass


class CornerStrategy(CropStrategy):
    """Изменение размера за угол: угол-якорь неподвижен, противоположный угол
    следует за курсором. anchor — «tl»/«tr»/«bl»/«br».
    """

    def __init__(self, anchor_type: str):
        self.anchor = anchor_type

    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        if self.anchor == "tl":
            return QRect(pos, rect.bottomRight())
        if self.anchor == "tr":
            return QRect(QPoint(rect.left(), pos.y()), QPoint(pos.x(), rect.bottom()))
        if self.anchor == "bl":
            return QRect(QPoint(pos.x(), rect.top()), QPoint(rect.right(), pos.y()))
        if self.anchor == "br":
            return QRect(rect.topLeft(), pos)
        return rect


class SideStrategy(CropStrategy):
    """Изменение размера за сторону: противоположная сторона неподвижна,
    размер меняется по одной оси. side — «top»/«bottom»/«left»/«right».
    """

    def __init__(self, side: str):
        self.side = side

    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        if self.side == "top":
            return QRect(QPoint(rect.left(), pos.y()), rect.bottomRight())
        if self.side == "bottom":
            return QRect(rect.left(), rect.top(), rect.width(), pos.y() - rect.top())
        if self.side == "left":
            return QRect(QPoint(pos.x(), rect.top()), rect.bottomRight())
        if self.side == "right":
            return QRect(rect.left(), rect.top(), pos.x() - rect.left(), rect.height())
        return rect


class PanStrategy(CropStrategy):
    """Перемещение выделения без изменения размера."""

    def __init__(self):
        self.drag_start = QPoint()
        self.rect_on_press = QRect()

    def on_mouse_press(self, pos: QPoint, rect: QRect):
        self.drag_start = pos
        self.rect_on_press = rect

    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        # Всё выделение сдвигается на вектор движения мыши относительно точки
        # нажатия, не меняя размера. Сдвиг относительно drag_start применяется
        # к прямоугольнику, запомненному на нажатии (rect_on_press), а не к уже
        # сдвинутому текущему rect, поэтому перемещение не накапливается в
        # цепочке mouse-move.
        delta = pos - self.drag_start
        new_tl = self.rect_on_press.topLeft() + delta
        new_br = self.rect_on_press.bottomRight() + delta
        return QRect(new_tl, new_br)


class CreateStrategy(CropStrategy):
    """Создание нового выделения: начальная точка фиксируется на нажатии,
    прямоугольник растёт из неё до курсора.
    """

    def __init__(self):
        self.begin = QPoint()

    def on_mouse_press(self, pos: QPoint, rect: QRect):
        self.begin = pos

    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        return QRect(self.begin, pos)
