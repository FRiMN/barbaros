"""Tests for crop frame rendering"""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent

from barbaros.widgets.image_crop.crop_selection import (
    BRACKET_SIDES,
    MASK_ALPHA,
    CropSelection,
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
)  # (35, 60, 80): color under black alpha=128
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
    widget = CropSelection(image)
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


# ---------- pure geometry ----------


def test_round_half_away_from_zero_like_pix_iround():
    # round_half_up was renamed to round_half_away_from_zero; a half is still
    # rounded away from zero (like iround in Pix).
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
    # The same delta magnitude in plus and minus must give the same
    # step in absolute value, otherwise the handle jerks in only one direction.
    assert round_half_away_from_zero(value) == expected
    assert round_half_away_from_zero(-value) == -expected


def test_hit_border_rule():
    assert hit_border(400, 400) == 40
    assert hit_border(90, 400) == 30   # width < 120
    assert hit_border(400, 90) == 30   # height < 120
    assert hit_border(90, 60) == 20    # height overrides width
    assert hit_border(6, 6) == 3       # minimum


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
    assert point_in_zone(50, 50, zone)   # right/bottom border is inclusive
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


# ---------- hit-test through the widget ----------


def test_hit_test_priority():
    widget = make_widget()
    assert widget.get_handle_at(QPoint(19, 19)) == HandlePos.TOP_LEFT
    assert widget.get_handle_at(QPoint(39, 39)) == HandlePos.TOP_LEFT  # corner takes precedence over side
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
    # scale == 0.5: 11*0.5=5.5 -> 6, 21*0.5=10.5 -> 11 (floor(x+0.5), not int/round)
    disp = widget._selection_screen_rect()
    assert (disp.x(), disp.y(), disp.width(), disp.height()) == (6, 6, 11, 11)


# ---------- rendering ----------


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

    # the old orange handles must not be drawn
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
    widget._update_cursor(QPoint(20, 20))  # top-left corner
    assert widget.cursor().shape() == Qt.CursorShape.SizeFDiagCursor


# ---------- drag: the selection moves relative to the press ----------
#
# The handles are invisible and occupy a zone of up to 40 px, so a press almost
# never lands exactly on the edge. Previously the edge would "stick" to the
# cursor on the very first mouse-move — the selection jumped. Expected behavior
# (like dragStart/dragStartSel in Pix): the edge is shifted exactly by the mouse
# delta from the press point, the distance from the cursor to the edge is
# preserved.


def press(widget: CropSelection, pos: QPoint):
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


def move(widget: CropSelection, pos: QPoint):
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
    # A press at (70,70) is the bottom-right zone, while the selection edge runs
    # along x/y = 79. Without a mouse delta the selection must stay unchanged.
    widget = make_widget()
    press(widget, QPoint(70, 70))
    assert widget.active_handle == HandlePos.BOTTOM_RIGHT
    move(widget, QPoint(70, 70))
    assert widget.get_crop_rect() == DEFAULT_SELECTION


def test_corner_drag_moves_edge_by_mouse_delta():
    widget = make_widget()
    press(widget, QPoint(70, 70))  # inside the bottom-right zone, 9 px from the edge
    move(widget, QPoint(72, 72))
    # The bottom-right corner shifted by 2 instead of jumping to the cursor position (72,72).
    assert widget.get_crop_rect() == QRect(20, 20, 62, 62)


def test_corner_drag_keeps_cursor_to_edge_distance():
    widget = make_widget()
    press(widget, QPoint(75, 75))
    move(widget, QPoint(80, 80))
    # The selection edge was at 79, the press cursor at 75 (a 4 px gap). After
    # a 5 px delta the edge goes to 84, and the gap remains 4 px.
    assert widget.get_crop_rect().bottomRight() == QPoint(84, 84)


def test_side_drag_changes_one_axis():
    widget = make_widget()
    press(widget, QPoint(50, 25))  # top-center zone
    move(widget, QPoint(50, 30))
    # The top side was at 20 and shifted by 5; the width did not change.
    assert widget.get_crop_rect() == QRect(20, 25, 60, 55)


def test_interior_drag_pans_selection():
    widget = make_widget()
    press(widget, QPoint(50, 50))
    move(widget, QPoint(60, 55))
    assert widget.get_crop_rect() == QRect(30, 25, 60, 60)


def test_create_from_outside_uses_press_point():
    widget = make_widget()
    press(widget, QPoint(5, 5))  # outside the selection — creation mode
    assert widget.active_handle == HandlePos.NONE
    move(widget, QPoint(60, 60))
    assert widget.get_crop_rect() == QRect(5, 5, 56, 56)


def test_drag_delta_is_converted_to_image_pixels():
    # A 200×200 image is fitted into 100×100 => scale 0.5: a 10 px mouse delta
    # corresponds to 20 image px.
    widget = make_widget(selection=QRect(20, 20, 60, 60), image_size=(200, 200), view=(100, 100))
    press(widget, QPoint(35, 35))  # screen bottom-right zone
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
