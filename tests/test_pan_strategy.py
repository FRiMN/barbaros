"""Tests for PanStrategy from barbaros.widgets.image_crop.transform_strategy.

PanStrategy is the "drag the selection" strategy (drag-to-pan): as the mouse
moves, the whole selection is shifted by the same vector without changing its
size. Strategy contract: on_mouse_press remembers the press point and the
rectangle at the moment of press, on_mouse_move receives the cursor delta from
the press point. The delta is applied to the rectangle at press time, so the
movement does not accumulate over a series of moves (see
test_pan_multiple_moves_preserve_size and
test_pan_no_accumulation_single_move_equals_sequence).
"""
import pytest
from PySide6.QtCore import QPoint, QRect, QSize

from barbaros.widgets.image_crop.transform_strategy import PanStrategy


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    """QApplication is not needed for these tests, but it keeps Qt quiet."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _drag(rect, press, delta):
    """Simulate the full cycle: press -> move the mouse by delta."""
    strat = PanStrategy()
    strat.on_mouse_press(press, rect)
    return strat.on_mouse_move(delta)


def test_pan_translates_by_mouse_delta():
    # Pressed at (10,10) and moved the mouse by (30,20)
    # => the selection shifted by (30,20).
    result = _drag(QRect(0, 0, 200, 100), QPoint(10, 10), QPoint(30, 20))
    assert result.topLeft() == QPoint(30, 20)
    # QRect.bottomRight() is the inclusive last pixel coordinate
    # (x + width - 1), hence (229, 119), not (230, 120).
    assert result.bottomRight() == QPoint(229, 119)
    assert result.size() == QSize(200, 100)


def test_pan_preserves_size():
    original = QRect(0, 0, 200, 100)
    result = _drag(original, QPoint(10, 10), QPoint(30, 20))
    assert result.size() == original.size() == QSize(200, 100)


def test_pan_zero_delta_returns_equal_rect():
    rect = QRect(5, 5, 100, 50)
    # The mouse did not move relative to the press point.
    result = _drag(rect, QPoint(50, 50), QPoint(0, 0))
    assert result == rect


def test_pan_negative_delta_moves_up_left():
    result = _drag(QRect(50, 50, 200, 100), QPoint(100, 100), QPoint(-20, -10))
    assert result.topLeft() == QPoint(30, 40)
    assert result.size() == QSize(200, 100)


def test_pan_press_stores_anchor_state():
    strat = PanStrategy()
    rect = QRect(50, 50, 200, 100)
    strat.on_mouse_press(QPoint(120, 80), rect)
    assert strat.drag_start == QPoint(120, 80)
    assert strat.rect_on_press == rect


def test_pan_multiple_moves_preserve_size():
    # A real drag = press, then several mouse moves, each time with an already
    # shifted selection_rect. The size must stay stable at every step, and the
    # position must depend only on the delta from the press point, not on the
    # number of steps (otherwise the movement "accumulates"/accelerates).
    strat = PanStrategy()
    rect = QRect(0, 0, 200, 100)
    strat.on_mouse_press(QPoint(0, 0), rect)

    step1 = strat.on_mouse_move(QPoint(10, 10))
    assert step1.topLeft() == QPoint(10, 10)
    assert step1.size() == QSize(200, 100)

    step2 = strat.on_mouse_move(QPoint(25, 40))
    assert step2.topLeft() == QPoint(25, 40)
    assert step2.size() == QSize(200, 100)

    step3 = strat.on_mouse_move(QPoint(5, 5))
    assert step3.topLeft() == QPoint(5, 5)
    assert step3.size() == QSize(200, 100)


def test_pan_no_accumulation_single_move_equals_sequence():
    # Regression test for the "acceleration"/accumulation effect.
    #
    # Key expectation: moving the selection in ONE step to the final point
    # must coincide with a series of moves ending at the same point. If the
    # delta accumulates (each move shifts the already shifted rect by the
    # vector to the press point), the series takes the rect farther than a
    # single move — this is the observed "acceleration" of the selection
    # behind the mouse.
    final_delta = QPoint(60, 45)
    original = QRect(0, 0, 200, 100)

    # A single move straight to the final point.
    single = _drag(original, QPoint(0, 0), final_delta)
    assert single.topLeft() == final_delta

    # A series of moves passing successively through different points and
    # ending at the same final_delta.
    strat = PanStrategy()
    strat.on_mouse_press(QPoint(0, 0), original)
    r = strat.on_mouse_move(QPoint(10, 10))
    r = strat.on_mouse_move(QPoint(25, 40))
    r = strat.on_mouse_move(final_delta)

    # The size does not change during the move…
    assert r.size() == original.size() == QSize(200, 100)
    # …and the result does not depend on the number of intermediate steps:
    # a series == a single move.
    assert r == single
