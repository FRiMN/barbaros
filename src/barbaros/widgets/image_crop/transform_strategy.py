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


from barbaros.widgets.image_crop.crop_selection import HandlePos

class CornerStrategy(CropStrategy):
    """Изменение размера за угол: угол-якорь неподвижен, противоположный угол
    следует за курсором.
    """

    def __init__(self, anchor: HandlePos):
        self.anchor = anchor

    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        match self.anchor:
            case HandlePos.TOP_LEFT:
                return QRect(pos, rect.bottomRight())
            case HandlePos.TOP_RIGHT:
                return QRect(QPoint(rect.left(), pos.y()), QPoint(pos.x(), rect.bottom()))
            case HandlePos.BOTTOM_LEFT:
                return QRect(QPoint(pos.x(), rect.top()), QPoint(rect.right(), pos.y()))
            case HandlePos.BOTTOM_RIGHT:
                return QRect(rect.topLeft(), pos)
            case _:
                return rect


class SideStrategy(CropStrategy):
    """Изменение размера за сторону: противоположная сторона неподвижна,
    размер меняется по одной оси.
    """

    def __init__(self, anchor: HandlePos):
        self.anchor = anchor

    def on_mouse_move(self, rect: QRect, pos: QPoint) -> QRect:
        match self.anchor:
            case HandlePos.TOP_CENTER:
                return QRect(QPoint(rect.left(), pos.y()), rect.bottomRight())
            case HandlePos.BOTTOM_CENTER:
                return QRect(rect.left(), rect.top(), rect.width(), pos.y() - rect.top())
            case HandlePos.LEFT_CENTER:
                return QRect(QPoint(pos.x(), rect.top()), rect.bottomRight())
            case HandlePos.RIGHT_CENTER:
                return QRect(rect.left(), rect.top(), pos.x() - rect.left(), rect.height())
            case _:
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
