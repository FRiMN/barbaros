"""Tests for CornerStrategy from barbaros.widgets.image_crop.transform_strategy.

CornerStrategy resizes the selection by a corner. Strategy contract:
  * on_mouse_press remembers the press point and the selection at the moment of press;
  * on_mouse_move receives the cursor DELTA from the press point and returns
    the selection built from the selection at the moment of press.

Therefore the corner being dragged moves exactly by the mouse delta, while the
opposite corner (the anchor) stays fixed. The absolute cursor position is not
used: the handles are invisible and can be pressed with a tolerance of a zone of
tens of pixels; otherwise the selection would "jump" to the cursor.
"""
import pytest
from PySide6.QtCore import QPoint, QRect

from barbaros.widgets.image_crop.transform_strategy import CornerStrategy, HandlePos


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    """QApplication is not needed for these tests, but it keeps Qt quiet."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _drag(anchor, press, delta, rect):
    """Simulate the full cycle: press a corner -> move the mouse by delta."""
    strat = CornerStrategy(anchor)
    strat.on_mouse_press(press, rect)
    return strat.on_mouse_move(delta)


# 50,40,200,150 → left=50, top=40, right=249, bottom=189, bottomRight=(249,189)
RECT = QRect(50, 40, 200, 150)
TL = QPoint(50, 40)
BR = QPoint(249, 189)


def test_valid_corner_anchors_accepted():
    for anchor in CornerStrategy.valid_handle_pos:
        # Must not raise.
        CornerStrategy(anchor)


@pytest.mark.parametrize("anchor", [HandlePos.NONE, HandlePos.INSIDE, HandlePos.TOP_CENTER])
def test_invalid_anchor_raises(anchor):
    with pytest.raises(ValueError):
        CornerStrategy(anchor)


@pytest.mark.parametrize("anchor", sorted(CornerStrategy.valid_handle_pos))
def test_no_delta_keeps_rect(anchor):
    # Pressed anywhere within the handle zone and did not move the mouse — the
    # selection must not change (regression: the corner used to jump to the
    # press point).
    for press in (QPoint(0, 0), QPoint(200, 150), QPoint(249, 189)):
        assert _drag(anchor, press, QPoint(0, 0), RECT) == RECT


@pytest.mark.parametrize(
    ("anchor", "delta", "expected"),
    [
        # The delta is applied to the corner being dragged; the anchor stays fixed.
        (HandlePos.TOP_LEFT, QPoint(-10, -5), QRect(40, 35, 210, 155)),
        (HandlePos.TOP_RIGHT, QPoint(10, -5), QRect(50, 35, 210, 155)),
        (HandlePos.BOTTOM_LEFT, QPoint(-10, 5), QRect(40, 40, 210, 155)),
        (HandlePos.BOTTOM_RIGHT, QPoint(10, 5), QRect(50, 40, 210, 155)),
    ],
)
def test_dragged_corner_moves_by_delta(anchor, delta, expected):
    # Press inside the handle zone, not exactly at the corner: this must not
    # affect the result — only the delta matters.
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
    # One corner follows the delta regardless of where exactly inside the zone
    # the press happened: a (0,0) delta from any point yields the original
    # rectangle.
    for press in (QPoint(0, 0), QPoint(200, 150), QPoint(249, 189)):
        assert _drag(anchor, press, QPoint(0, 0), RECT) == RECT


def test_corner_resize_can_shrink_and_grow():
    # Dragging the corner inward (shrink) and outward (grow) changes the size.
    shrink = _drag(HandlePos.TOP_LEFT, QPoint(120, 90), QPoint(70, 50), RECT)
    grow = _drag(HandlePos.TOP_LEFT, QPoint(50, 40), QPoint(-80, -70), RECT)
    assert shrink.width() < RECT.width() and shrink.height() < RECT.height()
    assert grow.width() > RECT.width() and grow.height() > RECT.height()


def test_delta_is_relative_to_press_not_to_cursor():
    # Two presses at different points within the same zone with the same delta
    # give the same result: the absolute cursor position is not involved.
    near_corner = _drag(HandlePos.BOTTOM_RIGHT, BR, QPoint(20, 10), RECT)
    inside_zone = _drag(HandlePos.BOTTOM_RIGHT, QPoint(200, 150), QPoint(20, 10), RECT)
    assert near_corner == inside_zone
    assert near_corner.bottomRight() == BR + QPoint(20, 10)
