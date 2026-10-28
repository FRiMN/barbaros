"""Тесты для CornerStrategy из barbaros.widgets.image_crop.transform_strategy.

CornerStrategy меняет размер выделения за угол. Контракт стратегии:
  * on_mouse_press запоминает точку нажатия и выделение на момент нажатия;
  * on_mouse_move получает СДВИГ курсора от точки нажатия и возвращает
    выделение, построенное от выделения на момент нажатия.
Поэтому угол, за который взялись, смещается ровно на сдвиг мыши, а
противоположный (якорь) остаётся неподвижным. Абсолютная позиция курсора не
используется: ручки невидимы и нажимать на них можно с точностью до зоны в
десятки пикселей, иначе выделение «прыгало» бы к курсору.
"""
import pytest
from PySide6.QtCore import QPoint, QRect

from barbaros.widgets.image_crop.transform_strategy import CornerStrategy, HandlePos


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    """QApplication нужен не для этих тестов, но снимает вопросы у Qt."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _drag(anchor, press, delta, rect):
    """Симулируем полный цикл: нажали за угол -> сдвинули мышь на delta."""
    strat = CornerStrategy(anchor)
    strat.on_mouse_press(press, rect)
    return strat.on_mouse_move(delta)


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


@pytest.mark.parametrize("anchor", sorted(CornerStrategy.valid_handle_pos))
def test_no_delta_keeps_rect(anchor):
    # Нажали в любом месте зоны ручки и не сдвинули мышь — выделение не должно
    # измениться (регрессия: раньше угол прыгал в точку нажатия).
    for press in (QPoint(0, 0), QPoint(200, 150), QPoint(249, 189)):
        assert _drag(anchor, press, QPoint(0, 0), RECT) == RECT


@pytest.mark.parametrize(
    ("anchor", "delta", "expected"),
    [
        # Сдвиг применяется к тому углу, за который тянут; якорь неподвижен.
        (HandlePos.TOP_LEFT, QPoint(-10, -5), QRect(40, 35, 210, 155)),
        (HandlePos.TOP_RIGHT, QPoint(10, -5), QRect(50, 35, 210, 155)),
        (HandlePos.BOTTOM_LEFT, QPoint(-10, 5), QRect(40, 40, 210, 155)),
        (HandlePos.BOTTOM_RIGHT, QPoint(10, 5), QRect(50, 40, 210, 155)),
    ],
)
def test_dragged_corner_moves_by_delta(anchor, delta, expected):
    # Нажатие внутри зоны ручки, не точно в угол: это не должно влиять на
    # результат — важна только величина сдвига.
    press = QPoint(220, 170)
    assert _drag(anchor, press, delta, RECT) == expected


@pytest.mark.parametrize(
    ("anchor", "anchor_point"),
    [
        (HandlePos.TOP_LEFT, BR),
        (HandlePos.TOP_RIGHT, QPoint(50, 189)),
        (HandlePos.BOTTOM_LEFT, QPoint(249, 40)),
        (HandlePos.BOTTOM_RIGHT, TL),
    ],
)
def test_opposite_corner_stays_fixed(anchor, anchor_point):
    result = _drag(anchor, QPoint(120, 120), QPoint(17, -9), RECT)
    corners = {result.topLeft(), result.topRight(), result.bottomLeft(), result.bottomRight()}
    assert anchor_point in corners


@pytest.mark.parametrize("anchor", sorted(CornerStrategy.valid_handle_pos))
def test_result_is_rect(anchor):
    # Один угол следует за сдвигом независимо от того, где именно внутри зоны
    # произошло нажатие: сдвиг (0,0) от любой точки даёт исходный прямоугольник.
    for press in (QPoint(0, 0), QPoint(200, 150), QPoint(249, 189)):
        assert _drag(anchor, press, QPoint(0, 0), RECT) == RECT


def test_corner_resize_can_shrink_and_grow():
    # Перетягивание угла внутрь (уменьшение) и наружу (увеличение) меняет размер.
    shrink = _drag(HandlePos.TOP_LEFT, QPoint(120, 90), QPoint(70, 50), RECT)
    grow = _drag(HandlePos.TOP_LEFT, QPoint(50, 40), QPoint(-80, -70), RECT)
    assert shrink.width() < RECT.width() and shrink.height() < RECT.height()
    assert grow.width() > RECT.width() and grow.height() > RECT.height()


def test_delta_is_relative_to_press_not_to_cursor():
    # Два нажатия в разных точках одной зоны с одинаковым сдвигом дают
    # одинаковый результат: абсолютная позиция курсора не участвует.
    near_corner = _drag(HandlePos.BOTTOM_RIGHT, BR, QPoint(20, 10), RECT)
    inside_zone = _drag(HandlePos.BOTTOM_RIGHT, QPoint(200, 150), QPoint(20, 10), RECT)
    assert near_corner == inside_zone
    assert near_corner.bottomRight() == BR + QPoint(20, 10)
