"""Тесты отрисовки crop-рамки по спеке docs/specs/pix-crop-selector."""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent

from barbaros.widgets.image_crop.crop_selection import (
    BRACKET_SIDES,
    MASK_ALPHA,
    GimpStyleCropSelection,
    bracket_segments,
    handle_zones,
    hit_border,
    point_in_zone,
    round_half_away_from_zero,
)
from barbaros.widgets.image_crop.transform_strategy import HandlePos

IMAGE_COLOR_RGB = (70, 120, 160)
IMAGE_COLOR = QColor(*IMAGE_COLOR_RGB)
MASKED = tuple(
    int(channel * (255 - MASK_ALPHA) / 255 + 0.5) for channel in IMAGE_COLOR_RGB
)  # (35, 60, 80): цвет под чёрным alpha=128
DIFFERENCE = tuple(255 - channel for channel in IMAGE_COLOR_RGB)  # (185, 135, 95)

DEFAULT_SELECTION = QRect(20, 20, 60, 60)


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def make_widget(
    selection=DEFAULT_SELECTION, image_size=(100, 100), view=(100, 100)
):
    image = QImage(image_size[0], image_size[1], QImage.Format.Format_RGB32)
    image.fill(IMAGE_COLOR)
    widget = GimpStyleCropSelection(image)
    widget.update_fit_scale(view[0], view[1])
    widget.set_crop_rect(selection)
    return widget


def render(widget) -> QImage:
    image = QImage(widget.size(), QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.black)
    widget.render(image)
    return image


def pixel(image: QImage, x: int, y: int) -> tuple[int, int, int]:
    color = image.pixelColor(x, y)
    return (color.red(), color.green(), color.blue())


# ---------- чистая геометрия ----------


def test_round_half_away_from_zero_like_pix_iround():
    # round_half_up переименован в round_half_away_from_zero; половина всё так же
    # округляется от нуля (как iround в Pix).
    assert round_half_away_from_zero(10.5) == 11
    assert round_half_away_from_zero(10.4) == 10
    assert round_half_away_from_zero(0.5) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.4, 0), (0.5, 1), (1.5, 2), (2.6, 3),
        (-0.4, 0), (-0.5, -1), (-1.5, -2), (-2.6, -3),
    ],
)
def test_round_half_away_from_zero_symmetric(value, expected):
    # Одна и та же величина сдвига в плюс и в минус должна давать одинаковый
    # по модулю шаг, иначе ручка дёргается только в одну сторону.
    assert round_half_away_from_zero(value) == expected
    assert round_half_away_from_zero(-value) == -expected


def test_hit_border_rule():
    assert hit_border(400, 400) == 40
    assert hit_border(90, 400) == 30   # ширина < 120
    assert hit_border(400, 90) == 30   # высота < 120
    assert hit_border(90, 60) == 20    # высота перекрывает ширину
    assert hit_border(6, 6) == 3       # минимум


def test_handle_zones_geometry():
    zones = dict(handle_zones(20, 20, 60, 60))  # b=20
    assert zones[HandlePos.TOP_LEFT] == (19, 19, 20, 20)
    assert zones[HandlePos.BOTTOM_RIGHT] == (60, 60, 20, 20)
    assert zones[HandlePos.TOP_CENTER] == (39, 19, 21, 20)
    assert zones[HandlePos.LEFT_CENTER] == (19, 39, 20, 21)
    assert zones[HandlePos.INSIDE] == (19, 19, 61, 61)


def test_point_in_zone_includes_right_and_bottom():
    zone = (20, 20, 30, 30)
    assert point_in_zone(20, 20, zone)
    assert point_in_zone(50, 50, zone)   # правая/нижняя граница включена
    assert not point_in_zone(51, 50, zone)
    assert not point_in_zone(19, 20, zone)


def test_bracket_sides_table():
    assert len(BRACKET_SIDES) == 8
    assert HandlePos.NONE not in BRACKET_SIDES
    assert HandlePos.INSIDE not in BRACKET_SIDES


def test_corner_bracket_has_two_lines():
    zone = dict(handle_zones(20, 20, 60, 60))[HandlePos.TOP_LEFT]
    segments = bracket_segments(zone, HandlePos.TOP_LEFT)
    assert len(segments) == 2
    points = [((a.x(), a.y()), (b.x(), b.y())) for a, b in segments]
    assert points == [
        ((38.5, 19.5), (38.5, 38.5)),
        ((19.5, 38.5), (38.5, 38.5)),
    ]


def test_side_bracket_has_three_lines():
    zone = dict(handle_zones(20, 20, 60, 60))[HandlePos.TOP_CENTER]
    segments = bracket_segments(zone, HandlePos.TOP_CENTER)
    assert len(segments) == 3
    assert {a.x() for a, _ in segments} == {39.5, 59.5}
    assert any(a.y() == b.y() == 38.5 for a, b in segments)


# ---------- hit-test через виджет ----------


def test_hit_test_priority():
    widget = make_widget()
    assert widget.get_handle_at(QPoint(19, 19)) == HandlePos.TOP_LEFT
    assert widget.get_handle_at(QPoint(39, 39)) == HandlePos.TOP_LEFT  # угол важнее стороны
    assert widget.get_handle_at(QPoint(40, 40)) == HandlePos.INSIDE
    assert widget.get_handle_at(QPoint(50, 25)) == HandlePos.TOP_CENTER
    assert widget.get_handle_at(QPoint(25, 50)) == HandlePos.LEFT_CENTER
    assert widget.get_handle_at(QPoint(50, 50)) == HandlePos.INSIDE
    assert widget.get_handle_at(QPoint(5, 50)) == HandlePos.NONE
    assert widget.get_handle_at(QPoint(61, 61)) == HandlePos.BOTTOM_RIGHT
    assert widget.get_handle_at(QPoint(80, 80)) == HandlePos.BOTTOM_RIGHT


def test_hit_test_empty_selection():
    widget = make_widget(selection=QRect(20, 20, 0, 0))
    assert widget.get_handle_at(QPoint(20, 20)) == HandlePos.NONE


def test_selection_screen_rect_independent_rounding():
    widget = make_widget(selection=QRect(11, 11, 21, 21), image_size=(200, 200), view=(100, 100))
    # scale == 0.5: 11*0.5=5.5 -> 6, 21*0.5=10.5 -> 11 (floor(x+0.5), не int/round)
    disp = widget._selection_screen_rect()
    assert (disp.x(), disp.y(), disp.width(), disp.height()) == (6, 6, 11, 11)


# ---------- отрисовка ----------


def test_plain_render_mask_border_no_handles():
    widget = make_widget()
    image = render(widget)
    assert pixel(image, 50, 50) == (70, 120, 160), "внутри выделения яркость исходная"
    assert pixel(image, 5, 50) == MASKED, "снаружи выделения затемнение 0.5"
    assert pixel(image, 50, 5) == MASKED
    assert pixel(image, 20, 50) == DIFFERENCE, "левая рамка = инверсия"
    assert pixel(image, 50, 20) == DIFFERENCE, "верхняя рамка = инверсия"
    assert pixel(image, 79, 50) == DIFFERENCE, "правая рамка = инверсия"
    assert pixel(image, 50, 79) == DIFFERENCE, "нижняя рамка = инверсия"

    # старые оранжевые ручки не должны рисоваться
    for x in range(image.width()):
        for y in range(image.height()):
            assert pixel(image, x, y) != (255, 165, 0)


def test_mask_hidden_while_dragging():
    widget = make_widget()
    widget.is_selecting = True
    image = render(widget)
    assert pixel(image, 5, 50) == (70, 120, 160), "при драге затемнения нет"
    assert pixel(image, 20, 50) == DIFFERENCE, "рамка остаётся"


def test_empty_selection_hides_overlay():
    for selection in (QRect(20, 20, 0, 0), QRect(20, 20, 60, 0), QRect(20, 20, 0, 60)):
        image = render(make_widget(selection=selection))
        assert pixel(image, 5, 50) == (70, 120, 160)
        assert pixel(image, 50, 50) == (70, 120, 160)


def test_hover_corner_bracket():
    widget = make_widget()
    widget.hovered_handle = HandlePos.TOP_LEFT
    image = render(widget)
    assert pixel(image, 38, 30) == DIFFERENCE, "вертикаль скобки"
    assert pixel(image, 30, 38) == DIFFERENCE, "горизонталь скобки"
    assert pixel(image, 30, 30) == (70, 120, 160)


def test_hover_side_bracket():
    widget = make_widget()
    widget.hovered_handle = HandlePos.TOP_CENTER
    image = render(widget)
    assert pixel(image, 39, 25) == DIFFERENCE, "левая вертикаль"
    assert pixel(image, 59, 25) == DIFFERENCE, "правая вертикаль"
    assert pixel(image, 50, 38) == DIFFERENCE, "нижняя горизонталь"


def test_hover_interior_has_no_bracket():
    widget = make_widget()
    widget.hovered_handle = HandlePos.INSIDE
    image = render(widget)
    assert pixel(image, 38, 30) == (70, 120, 160)
    assert pixel(image, 30, 38) == (70, 120, 160)


def test_cursor_changes_with_zone():
    widget = make_widget()
    widget._update_cursor(QPoint(5, 50))
    assert widget.cursor().shape() == Qt.CursorShape.CrossCursor
    widget._update_cursor(QPoint(50, 50))
    assert widget.cursor().shape() == Qt.CursorShape.SizeAllCursor
    widget._update_cursor(QPoint(20, 20))  # верхний левый угол
    assert widget.cursor().shape() == Qt.CursorShape.SizeFDiagCursor


# ---------- драг: выделение двигается относительно нажатия ----------
#
# Ручки невидимы и занимают зону до 40 px, поэтому нажатие почти никогда не
# попадает точно в край. Раньше край «прилипал» к курсору на первом же
# mouse-move — выделение прыгало. Ожидаемое поведение (как dragStart/
# dragStartSel в Pix): край смещается ровно на сдвиг мыши от точки нажатия,
# расстояние от курсора до края сохраняется.


def press(widget: GimpStyleCropSelection, pos: QPoint):
    point = QPointF(pos)
    widget.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            point,
            point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def move(widget: GimpStyleCropSelection, pos: QPoint):
    point = QPointF(pos)
    widget.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            point,
            point,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def test_press_inside_handle_does_not_jump():
    # Нажатие в (70,70) — это зона bottom-right, а край выделения проходит по
    # x/y = 79. Без сдвига мыши выделение обязано остаться прежним.
    widget = make_widget()
    press(widget, QPoint(70, 70))
    assert widget.active_handle == HandlePos.BOTTOM_RIGHT
    move(widget, QPoint(70, 70))
    assert widget.get_crop_rect() == DEFAULT_SELECTION


def test_corner_drag_moves_edge_by_mouse_delta():
    widget = make_widget()
    press(widget, QPoint(70, 70))  # внутри зоны bottom-right, 9 px от края
    move(widget, QPoint(72, 72))
    # Правый-нижний угол сдвинулся на 2, а не прыгнул в позицию курсора (72,72).
    assert widget.get_crop_rect() == QRect(20, 20, 62, 62)


def test_corner_drag_keeps_cursor_to_edge_distance():
    widget = make_widget()
    press(widget, QPoint(75, 75))
    move(widget, QPoint(80, 80))
    # Край выделения был в 79, курсор нажатия — в 75 (зазор 4 px). После
    # сдвига на 5 px край идёт в 84, зазор остаётся 4 px.
    assert widget.get_crop_rect().bottomRight() == QPoint(84, 84)


def test_side_drag_changes_one_axis():
    widget = make_widget()
    press(widget, QPoint(50, 25))  # зона top-center
    move(widget, QPoint(50, 30))
    # Верхняя сторона была на 20 и сдвинулась на 5; ширина не изменилась.
    assert widget.get_crop_rect() == QRect(20, 25, 60, 55)


def test_interior_drag_pans_selection():
    widget = make_widget()
    press(widget, QPoint(50, 50))
    move(widget, QPoint(60, 55))
    assert widget.get_crop_rect() == QRect(30, 25, 60, 60)


def test_create_from_outside_uses_press_point():
    widget = make_widget()
    press(widget, QPoint(5, 5))  # вне выделения — режим создания
    assert widget.active_handle == HandlePos.NONE
    move(widget, QPoint(60, 60))
    assert widget.get_crop_rect() == QRect(5, 5, 56, 56)


def test_drag_delta_is_converted_to_image_pixels():
    # Изображение 200×200 вписано в 100×100 => scale 0.5: сдвиг мыши на 10 px
    # соответствует 20 px изображения.
    widget = make_widget(selection=QRect(20, 20, 60, 60), image_size=(200, 200), view=(100, 100))
    press(widget, QPoint(35, 35))  # экранная зона bottom-right
    assert widget.active_handle == HandlePos.BOTTOM_RIGHT
    move(widget, QPoint(45, 45))
    assert widget.get_crop_rect() == QRect(20, 20, 80, 80)


def test_release_resets_drag_state():
    widget = make_widget()
    press(widget, QPoint(70, 70))
    point = QPointF(QPoint(70, 70))
    widget.mouseReleaseEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            point,
            point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert widget.is_selecting is False
    assert widget.active_handle == HandlePos.NONE
