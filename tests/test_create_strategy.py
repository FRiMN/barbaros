"""Tests for CreateStrategy from barbaros.widgets.image_crop.transform_strategy.

CreateStrategy creates a new selection: the press point is fixed on press
(on_mouse_press), and the rectangle grows from it by the cursor delta from that
point. The rectangle can be built in any direction (including "backwards",
left-up), so the result is usually normalized (CropSelection does this in
mouseMoveEvent via .normalized()); here the behavior of the strategy itself
is tested.
"""
import pytest
from PySide6.QtCore import QPoint, QRect

from barbaros.widgets.image_crop.transform_strategy import CreateStrategy


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    """QApplication is not needed for these tests, but it keeps Qt quiet."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _drag(begin, delta):
    """Simulate the full cycle: press at begin -> move the mouse by delta."""
    strat = CreateStrategy()
    strat.on_mouse_press(begin, QRect())
    return strat.on_mouse_move(delta)


def test_press_fixes_begin_point():
    strat = CreateStrategy()
    strat.on_mouse_press(QPoint(123, 45), QRect())
    assert strat.drag_start == QPoint(123, 45)


def test_move_builds_rect_from_begin_to_delta():
    result = _drag(QPoint(100, 100), QPoint(150, 80))
    assert result.topLeft() == QPoint(100, 100)
    assert result.bottomRight() == QPoint(250, 180)
    assert result.width() == 151  # 250 - 100 + 1 (QRect is inclusive)
    assert result.height() == 81  # 180 - 100 + 1


def test_move_supports_negative_direction():
    # Dragging left-up: begin is at the bottom-right, the delta is negative.
    # The strategy itself just builds QRect(begin, begin+delta) — it may be
    # "inverted"; CropSelection normalizes the result.
    result = _drag(QPoint(250, 180), QPoint(-150, -80))
    assert result == QRect(QPoint(250, 180), QPoint(100, 100))
    norm = result.normalized()
    assert norm.width() > 0 and norm.height() > 0


def test_zero_delta_is_single_pixel():
    # An exact press with no movement — a 1x1 rectangle (QRect is inclusive).
    result = _drag(QPoint(100, 100), QPoint(0, 0))
    assert result == QRect(100, 100, 1, 1)


def test_begin_survives_between_press_and_move():
    # on_mouse_move reads the press point stored on press, not the current rect.
    strat = CreateStrategy()
    strat.on_mouse_press(QPoint(10, 20), QRect())
    first = strat.on_mouse_move(QPoint(20, 20))
    second = strat.on_mouse_move(QPoint(30, 30))
    assert first.topLeft() == QPoint(10, 20)
    assert second.topLeft() == QPoint(10, 20)
    assert second.bottomRight() == QPoint(40, 50)
