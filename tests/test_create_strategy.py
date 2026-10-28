"""Тесты для CreateStrategy из barbaros.widgets.image_crop.transform_strategy.

CreateStrategy создаёт новое выделение: точка нажатия фиксируется на нажатии
(on_mouse_press), прямоугольник растёт из неё на сдвиг курсора от этой точки.
Прямоугольник может строиться в любом направлении (в т.ч. «назад», влево-вверх),
поэтому результат обычно нормализуют (это делает GimpStyleCropSelection в
mouseMoveEvent через .normalized()); здесь тестируется поведение самой
стратегии.
"""
import pytest
from PySide6.QtCore import QPoint, QRect

from barbaros.widgets.image_crop.transform_strategy import CreateStrategy


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    """QApplication нужен не для этих тестов, но снимает вопросы у Qt."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _drag(begin, delta):
    """Симулируем полный цикл: нажали в begin -> сдвинули мышь на delta."""
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
    assert result.width() == 151  # 250 - 100 + 1 (QRect включительный)
    assert result.height() == 81  # 180 - 100 + 1


def test_move_supports_negative_direction():
    # Тянем влево-вверх: begin в правом-нижнем, сдвиг отрицательный.
    # Сама стратегия просто строит QRect(begin, begin+delta) — он может быть
    # «перевёрнутым»; нормализует результат GimpStyleCropSelection.
    result = _drag(QPoint(250, 180), QPoint(-150, -80))
    assert result == QRect(QPoint(250, 180), QPoint(100, 100))
    norm = result.normalized()
    assert norm.width() > 0 and norm.height() > 0


def test_zero_delta_is_single_pixel():
    # Точное нажатие без движения — прямоугольник 1x1 (QRect включительный).
    result = _drag(QPoint(100, 100), QPoint(0, 0))
    assert result == QRect(100, 100, 1, 1)


def test_begin_survives_between_press_and_move():
    # on_mouse_move читает точку нажатия, запомненную на press, а не текущий rect.
    strat = CreateStrategy()
    strat.on_mouse_press(QPoint(10, 20), QRect())
    first = strat.on_mouse_move(QPoint(20, 20))
    second = strat.on_mouse_move(QPoint(30, 30))
    assert first.topLeft() == QPoint(10, 20)
    assert second.topLeft() == QPoint(10, 20)
    assert second.bottomRight() == QPoint(40, 50)
