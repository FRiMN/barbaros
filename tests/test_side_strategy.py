"""Тесты для SideStrategy из barbaros.widgets.image_crop.transform_strategy.

SideStrategy меняет размер выделения за сторону (ручку в середине края):
противоположная сторона неподвижна, сторона под курсором смещается на сдвиг
мыши по своей оси.
  TOP_CENTER / BOTTOM_CENTER — двигается верх/низ, ширина (X) фиксирована.
  LEFT_CENTER / RIGHT_CENTER — двигается лево/право, высота (Y) фиксирована.

Контракт: on_mouse_move получает СДВИГ курсора от точки нажатия, а не его
абсолютную позицию, поэтому нажатие внутри зоны ручки (до 40 px) не даёт скачка.
"""
import pytest
from PySide6.QtCore import QPoint, QRect

from barbaros.widgets.image_crop.transform_strategy import HandlePos, SideStrategy


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    """QApplication нужен не для этих тестов, но снимает вопросы у Qt."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _drag(anchor, press, delta, rect):
    """Симулируем полный цикл: нажали за сторону -> сдвинули мышь на delta."""
    strat = SideStrategy(anchor)
    strat.on_mouse_press(press, rect)
    return strat.on_mouse_move(delta)


RECT = QRect(50, 40, 200, 150)
LEFT, TOP, WIDTH, HEIGHT = 50, 40, 200, 150


def test_valid_side_anchors_accepted():
    for anchor in SideStrategy.valid_handle_pos:
        SideStrategy(anchor)


@pytest.mark.parametrize("anchor", [HandlePos.NONE, HandlePos.INSIDE, HandlePos.TOP_LEFT])
def test_invalid_anchor_raises(anchor):
    with pytest.raises(ValueError):
        SideStrategy(anchor)


@pytest.mark.parametrize("anchor", sorted(SideStrategy.valid_handle_pos))
def test_no_delta_keeps_rect(anchor):
    # Нажали внутри зоны ручки и не сдвинули мышь — размер и положение те же
    # (регрессия: раньше сторона прыгала в координату курсора).
    for press in (QPoint(0, 0), QPoint(150, 115), QPoint(249, 189)):
        assert _drag(anchor, press, QPoint(0, 0), RECT) == RECT


@pytest.mark.parametrize(
    ("anchor", "delta", "expected"),
    [
        # Двигается только сторона под курсором; остальное — неподвижно.
        (HandlePos.TOP_CENTER, QPoint(0, -10), QRect(50, 30, 200, 160)),
        (HandlePos.BOTTOM_CENTER, QPoint(0, 10), QRect(50, 40, 200, 160)),
        (HandlePos.LEFT_CENTER, QPoint(-10, 0), QRect(40, 40, 210, 150)),
        (HandlePos.RIGHT_CENTER, QPoint(10, 0), QRect(50, 40, 210, 150)),
    ],
)
def test_dragged_side_moves_by_delta(anchor, delta, expected):
    # Нажатие внутри зоны, не точно в сторону: на результат не влияет.
    press = QPoint(112, 108)
    assert _drag(anchor, press, delta, RECT) == expected


@pytest.mark.parametrize(
    ("anchor", "delta", "on_axis"),
    [
        # Сторона двигается только по своей оси: сдвиг по второй оси ни на что не влияет.
        (HandlePos.TOP_CENTER, QPoint(100, -10), QPoint(0, -10)),
        (HandlePos.BOTTOM_CENTER, QPoint(100, 10), QPoint(0, 10)),
        (HandlePos.LEFT_CENTER, QPoint(-10, 100), QPoint(-10, 0)),
        (HandlePos.RIGHT_CENTER, QPoint(10, 100), QPoint(10, 0)),
    ],
)
def test_cross_axis_delta_is_ignored(anchor, delta, on_axis):
    press = QPoint(112, 108)
    assert _drag(anchor, press, delta, RECT) == _drag(anchor, press, on_axis, RECT)


def test_side_resize_shrinks_and_grows_per_axis():
    grow = _drag(HandlePos.LEFT_CENTER, QPoint(50, 100), QPoint(-30, 0), RECT)
    shrink = _drag(HandlePos.LEFT_CENTER, QPoint(50, 100), QPoint(120, 0), RECT)
    assert grow.width() > WIDTH
    assert shrink.width() < WIDTH
    # По оси Y размер не меняется ни при каком ходе.
    assert grow.height() == HEIGHT
    assert shrink.height() == HEIGHT
    # Правая сторона (якорь) неподвижна в обоих случаях.
    assert grow.right() == shrink.right() == LEFT + WIDTH - 1


def test_opposite_side_stays_fixed():
    # Верхняя сторона тянется вверх: низ не двигается.
    top = _drag(HandlePos.TOP_CENTER, QPoint(112, 108), QPoint(0, -10), RECT)
    assert (top.left(), top.right(), top.bottom()) == (LEFT, LEFT + WIDTH - 1, TOP + HEIGHT - 1)

    # Нижняя сторона тянется вниз: верх не двигается.
    bottom = _drag(HandlePos.BOTTOM_CENTER, QPoint(112, 108), QPoint(0, 10), RECT)
    assert (bottom.left(), bottom.right(), bottom.top()) == (LEFT, LEFT + WIDTH - 1, TOP)

    # Левая сторона тянется влево: правая не двигается.
    left = _drag(HandlePos.LEFT_CENTER, QPoint(112, 108), QPoint(-10, 0), RECT)
    assert (left.top(), left.bottom(), left.right()) == (TOP, TOP + HEIGHT - 1, LEFT + WIDTH - 1)

    # Правая сторона тянется вправо: левая не двигается.
    right = _drag(HandlePos.RIGHT_CENTER, QPoint(112, 108), QPoint(10, 0), RECT)
    assert (right.top(), right.bottom(), right.left()) == (TOP, TOP + HEIGHT - 1, LEFT)
