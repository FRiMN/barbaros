"""Тесты для CreateStrategy из barbaros.widgets.image_crop.transform_strategy.

CreateStrategy создаёт новое выделение: начальная точка фиксируется на нажатии
(on_mouse_press), прямоугольник растёт из неё до текущей позиции курсора.
Прямоугольник может строиться в любом направлении (в т.ч. «назад», влево-вверх),
поэтому результат обычно нормализуют (это делает GimpStyleCropSelection в
mousePressEvent через .normalized()); здесь тестируется поведение самой
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


def _press_move(begin, pos):
    """Симулируем полный цикл: нажали в begin -> передвинули мышь в pos."""
    strat = CreateStrategy()
    strat.on_mouse_press(QPoint(begin.x(), begin.y()), QRect())
    return strat.on_mouse_move(QRect(), pos)


def test_press_fixes_begin_point():
    strat = CreateStrategy()
    strat.on_mouse_press(QPoint(123, 45), QRect())
    assert strat.begin == QPoint(123, 45)


def test_move_builds_rect_from_begin_to_pos():
    result = _press_move(QPoint(100, 100), QPoint(250, 180))
    assert result.topLeft() == QPoint(100, 100)
    assert result.bottomRight() == QPoint(250, 180)
    assert result.width() == 151  # 250 - 100 + 1 (QRect включительный)
    assert result.height() == 81  # 180 - 100 + 1


def test_move_supports_negative_direction():
    # Тянем влево-вверх: begin в правом-нижнем, курсор в левом-верхнем.
    # Сама стратегия просто строит QRect(begin, pos) — он может быть отрицательным;
    # нормализует результат (GimpStyleCropSelection). Проверяем, что begin и
    # pos — концы прямоугольника и после нормализации получение валидно.
    strat = CreateStrategy()
    strat.on_mouse_press(QPoint(250, 180), QRect())
    result = strat.on_mouse_move(QRect(), QPoint(100, 100))
    assert result == QRect(QPoint(250, 180), QPoint(100, 100))
    norm = result.normalized()
    assert norm.width() > 0 and norm.height() > 0


def test_zero_delta_is_single_pixel():
    # Точное нажатие без движения — прямоугольник 1x1 (QRect включительный).
    result = _press_move(QPoint(100, 100), QPoint(100, 100))
    assert result == QRect(100, 100, 1, 1)


def test_begin_survives_between_press_and_move():
    # on_mouse_move читает begin, запомненный на нажатии, а не текущий rect.
    strat = CreateStrategy()
    strat.on_mouse_press(QPoint(10, 20), QRect())
    first = strat.on_mouse_move(QRect(), QPoint(30, 40))
    second = strat.on_mouse_move(first, QPoint(40, 50))
    assert first.topLeft() == QPoint(10, 20)
    assert second.topLeft() == QPoint(10, 20)
    assert second.bottomRight() == QPoint(40, 50)
