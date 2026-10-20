"""Тесты для CornerStrategy из barbaros.widgets.image_crop.transform_strategy.

CornerStrategy меняет размер выделения за угол: тянем за угол — этот угол
следует за курсором, а противоположный (диагонально противоположный) угол
остаётся неподвижным. Остальные два угла смещаются по одной оси каждый.

Именно так работает код, а не дословно так, как сформулировано в docstring
базового класса: например, при захвате TOP_LEFT угол-курор (top-left) уходит в
позицию мыши, а bottom-right остаётся на месте (QRect(pos, rect.bottomRight())).
Здесь valid_handle_pos — это ручки, которые можно перетаскивать, а не фиксированные
точки. Тесты проверяют фактическое поведение: какой угол зафиксирован, который
повторяет курсор и как меняется размер.
"""
import pytest
from PySide6.QtCore import QRect, QPoint

from barbaros.widgets.image_crop.transform_strategy import CornerStrategy, HandlePos


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    """QApplication нужен не для этих тестов, но снимает вопросы у Qt."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _press_move(anchor, pos, rect):
    """Симулируем полный цикл: нажали за угол -> передвинули мышь."""
    strat = CornerStrategy(anchor)
    strat.on_mouse_press(QPoint(0, 0), rect)
    return strat.on_mouse_move(rect, pos)


# 50,40,200,150 → left=50, top=40, right=249, bottom=189, bottomRight=(249,189)
RECT = QRect(50, 40, 200, 150)
TL = QPoint(50, 40)
BR = QPoint(249, 189)


def test_valid_corner_anchors_accepted():
    for anchor in CornerStrategy.valid_handle_pos:
        # Не должен бросать.
        CornerStrategy(anchor)


@pytest.mark.parametrize("anchor", [HandlePos.NONE, HandlePos.INSIDE, HandlePos.TOP_CENTER])
def test_invalid_anchor_raises(anchor):
    with pytest.raises(ValueError):
        CornerStrategy(anchor)


def test_top_left_moves_top_left_bottom_right_fixed():
    # Тянем за top-left в (20,10): левый-верхний идёт за курсором,
    # правый-нижний (якорь) на месте.
    result = _press_move(HandlePos.TOP_LEFT, QPoint(20, 10), RECT)
    assert result.topLeft() == QPoint(20, 10)
    assert result.bottomRight() == BR
    assert result.width() == 230  # 249 - 20 + 1 (QRect включительный)
    assert result.height() == 180  # 189 - 10 + 1


def test_top_right_moves_top_right_bottom_left_fixed():
    # Тянем за top-right в (320,10): правый-верхний идёт за курсором,
    # левый-нижний (якорь) на месте.
    result = _press_move(HandlePos.TOP_RIGHT, QPoint(320, 10), RECT)
    assert result.topRight() == QPoint(320, 10)
    assert result.left() == 50
    assert result.bottom() == 189
    assert result.width() == 271  # 320 - 50 + 1
    assert result.height() == 180  # 189 - 10 + 1


def test_bottom_left_moves_bottom_left_top_right_fixed():
    # Тянем за bottom-left в (20,260): левый-нижний идёт за курсором,
    # правый-верхний (якорь) на месте.
    result = _press_move(HandlePos.BOTTOM_LEFT, QPoint(20, 260), RECT)
    assert result.bottomLeft() == QPoint(20, 260)
    assert result.right() == 249
    assert result.top() == 40
    assert result.width() == 230  # 249 - 20 + 1
    assert result.height() == 221  # 260 - 40 + 1


def test_bottom_right_moves_bottom_right_top_left_fixed():
    # Тянем за bottom-right в (320,260): правый-нижний идёт за курсором,
    # левый-верхний (якорь) на месте.
    result = _press_move(HandlePos.BOTTOM_RIGHT, QPoint(320, 260), RECT)
    assert result.bottomRight() == QPoint(320, 260)
    assert result.topLeft() == TL
    assert result.width() == 271  # 320 - 50 + 1
    assert result.height() == 221  # 260 - 40 + 1


def test_corner_no_move_preserves_size():
    # Курсор в исходной точке угла — размер не меняется.
    result = _press_move(HandlePos.BOTTOM_RIGHT, BR, RECT)
    assert result.width() == RECT.width() == 200
    assert result.height() == RECT.height() == 150


def test_corner_resize_can_shrink_and_grow():
    # Перетягивание угла внутрь (уменьшение) и наружу (увеличение) меняет размер.
    shrink = _press_move(HandlePos.TOP_LEFT, QPoint(120, 90), RECT)
    grow = _press_move(HandlePos.TOP_LEFT, QPoint(-30, -30), RECT)
    assert shrink.width() < RECT.width() and shrink.height() < RECT.height()
    assert grow.width() > RECT.width() and grow.height() > RECT.height()
