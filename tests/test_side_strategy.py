"""Тесты для SideStrategy из barbaros.widgets.image_crop.transform_strategy.

SideStrategy меняет размер выделения за сторону (ручку в середине края):
противоположная сторона неподвижна, размер меняется только по одной оси.
  TOP_CENTER / BOTTOM_CENTER — двигается верх/низ, ширина (X) фиксирована.
  LEFT_CENTER / RIGHT_CENTER — двигается лево/право, высота (Y) фиксирована.

valid_handle_pos — это ручки, которые можно перетаскивать. Тесты проверяют
фактическое поведение: какая сторона зафиксирована и по какой оси меняется
размер.
"""
import pytest
from PySide6.QtCore import QPoint, QRect, QSize

from barbaros.widgets.image_crop.transform_strategy import HandlePos, SideStrategy


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    """QApplication нужен не для этих тестов, но снимает вопросы у Qt."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _press_move(anchor, pos, rect):
    """Симулируем полный цикл: нажали за сторону -> передвинули мышь."""
    strat = SideStrategy(anchor)
    strat.on_mouse_press(QPoint(0, 0), rect)
    return strat.on_mouse_move(rect, pos)


RECT = QRect(50, 40, 200, 150)
LEFT, TOP, WIDTH, HEIGHT = 50, 40, 200, 150


def test_valid_side_anchors_accepted():
    for anchor in SideStrategy.valid_handle_pos:
        SideStrategy(anchor)


@pytest.mark.parametrize("anchor", [HandlePos.NONE, HandlePos.INSIDE, HandlePos.TOP_LEFT])
def test_invalid_anchor_raises(anchor):
    with pytest.raises(ValueError):
        SideStrategy(anchor)


def test_top_center_changes_height_only_top_moves():
    # Тянем за верхнюю сторону вниз? нет — в (100,10) вверх: высота растёт,
    # лево/право/низ на месте.
    result = _press_move(HandlePos.TOP_CENTER, QPoint(100, 10), RECT)
    assert result.left() == LEFT
    assert result.right() == LEFT + WIDTH - 1
    assert result.bottom() == TOP + HEIGHT - 1
    assert result.top() == 10
    assert result.width() == WIDTH
    assert result.height() == 180  # 189 - 10 + 1 (QRect включительный)


def test_bottom_center_changes_height_only_bottom_moves():
    # Тянем за нижнюю сторону вниз в (150,260): низ уходит, верх/лево/право на месте.
    result = _press_move(HandlePos.BOTTOM_CENTER, QPoint(150, 260), RECT)
    assert result.top() == TOP
    assert result.left() == LEFT
    assert result.right() == LEFT + WIDTH - 1
    assert result.width() == WIDTH
    assert result.height() == 260 - TOP  # 220


def test_left_center_changes_width_only_left_moves():
    # Тянем за левую сторону влево в (10,100): лево уходит, верх/низ/право на месте.
    result = _press_move(HandlePos.LEFT_CENTER, QPoint(10, 100), RECT)
    assert result.top() == TOP
    assert result.bottom() == TOP + HEIGHT - 1
    assert result.right() == LEFT + WIDTH - 1
    assert result.left() == 10
    assert result.height() == HEIGHT
    assert result.width() == 240  # 249 - 10 + 1


def test_right_center_changes_width_only_right_moves():
    # Тянем за правую сторону вправо в (320,100): право уходит, лево/верх/низ на месте.
    result = _press_move(HandlePos.RIGHT_CENTER, QPoint(320, 100), RECT)
    assert result.left() == LEFT
    assert result.top() == TOP
    assert result.bottom() == TOP + HEIGHT - 1
    assert result.height() == HEIGHT
    assert result.width() == 320 - LEFT  # 270


def test_side_no_move_preserves_size():
    # Курсор в середине стороны без сдвига — размер не меняется.
    result = _press_move(HandlePos.TOP_CENTER, QPoint(150, TOP), RECT)
    assert result.size() == RECT.size() == QSize(WIDTH, HEIGHT)


def test_side_resize_shrinks_and_grows_per_axis():
    grow = _press_move(HandlePos.LEFT_CENTER, QPoint(-30, 100), RECT)
    shrink = _press_move(HandlePos.LEFT_CENTER, QPoint(120, 100), RECT)
    assert grow.width() > WIDTH
    assert shrink.width() < WIDTH
    # По оси Y размер не меняется ни при каком ходе.
    assert grow.height() == HEIGHT
    assert shrink.height() == HEIGHT
