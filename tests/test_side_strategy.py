"""Tests for SideStrategy from barbaros.widgets.image_crop.transform_strategy.

SideStrategy resizes the selection by a side (a handle in the middle of an edge):
the opposite side stays fixed, and the side under the cursor moves by the mouse
delta along its own axis.
  TOP_CENTER / BOTTOM_CENTER — the top/bottom moves, width (X) is fixed.
  LEFT_CENTER / RIGHT_CENTER — the left/right moves, height (Y) is fixed.

Contract: on_mouse_move receives the cursor DELTA from the press point, not its
absolute position, so pressing inside the handle zone (up to 40 px) does not
cause a jump.
"""
import pytest
from PySide6.QtCore import QPoint, QRect

from barbaros.widgets.image_crop.transform_strategy import HandlePos, SideStrategy


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    """QApplication is not needed for these tests, but it keeps Qt quiet."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _drag(anchor, press, delta, rect):
    """Simulate the full cycle: press a side -> move the mouse by delta."""
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
    # Pressed inside the handle zone and did not move the mouse — size and
    # position stay the same (regression: the side used to jump to the cursor
    # coordinate).
    for press in (QPoint(0, 0), QPoint(150, 115), QPoint(249, 189)):
        assert _drag(anchor, press, QPoint(0, 0), RECT) == RECT


@pytest.mark.parametrize(
    ("anchor", "delta", "expected"),
    [
        # Only the side under the cursor moves; everything else stays fixed.
        (HandlePos.TOP_CENTER, QPoint(0, -10), QRect(50, 30, 200, 160)),
        (HandlePos.BOTTOM_CENTER, QPoint(0, 10), QRect(50, 40, 200, 160)),
        (HandlePos.LEFT_CENTER, QPoint(-10, 0), QRect(40, 40, 210, 150)),
        (HandlePos.RIGHT_CENTER, QPoint(10, 0), QRect(50, 40, 210, 150)),
    ],
)
def test_dragged_side_moves_by_delta(anchor, delta, expected):
    # Press inside the zone, not exactly on the side: does not affect the result.
    press = QPoint(112, 108)
    assert _drag(anchor, press, delta, RECT) == expected


@pytest.mark.parametrize(
    ("anchor", "delta", "on_axis"),
    [
        # The side moves only along its own axis: a delta along the second axis
        # has no effect.
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
    # The size along Y does not change with any move.
    assert grow.height() == HEIGHT
    assert shrink.height() == HEIGHT
    # The right side (anchor) stays fixed in both cases.
    assert grow.right() == shrink.right() == LEFT + WIDTH - 1


def test_opposite_side_stays_fixed():
    # The top side is dragged up: the bottom does not move.
    top = _drag(HandlePos.TOP_CENTER, QPoint(112, 108), QPoint(0, -10), RECT)
    assert (top.left(), top.right(), top.bottom()) == (LEFT, LEFT + WIDTH - 1, TOP + HEIGHT - 1)

    # The bottom side is dragged down: the top does not move.
    bottom = _drag(HandlePos.BOTTOM_CENTER, QPoint(112, 108), QPoint(0, 10), RECT)
    assert (bottom.left(), bottom.right(), bottom.top()) == (LEFT, LEFT + WIDTH - 1, TOP)

    # The left side is dragged left: the right does not move.
    left = _drag(HandlePos.LEFT_CENTER, QPoint(112, 108), QPoint(-10, 0), RECT)
    assert (left.top(), left.bottom(), left.right()) == (TOP, TOP + HEIGHT - 1, LEFT + WIDTH - 1)

    # The right side is dragged right: the left does not move.
    right = _drag(HandlePos.RIGHT_CENTER, QPoint(112, 108), QPoint(10, 0), RECT)
    assert (right.top(), right.bottom(), right.left()) == (TOP, TOP + HEIGHT - 1, LEFT)
