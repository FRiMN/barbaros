"""Тесты для PanStrategy из barbaros.widgets.image_crop.transform_strategy.

PanStrategy — это стратегия «перетащить выделение» (drag-to-pan): при движении
мыши всё выделение сдвигается на тот же вектор, не меняя своего размера.
Контракт стратегии: on_mouse_press запоминает точку нажатия и прямоугольник на
момент нажатия, on_mouse_move получает сдвиг курсора от точки нажатия. Дельта
применяется к прямоугольнику на нажатии, поэтому перемещение не накапливается
за серию ходов (см. test_pan_multiple_moves_preserve_size и
test_pan_no_accumulation_single_move_equals_sequence).
"""
import pytest
from PySide6.QtCore import QPoint, QRect, QSize

from barbaros.widgets.image_crop.transform_strategy import PanStrategy


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    """QApplication нужен не для этих тестов, но снимает вопросы у Qt."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _drag(rect, press, delta):
    """Симулируем полный цикл: нажали -> сдвинули мышь на delta."""
    strat = PanStrategy()
    strat.on_mouse_press(press, rect)
    return strat.on_mouse_move(delta)


def test_pan_translates_by_mouse_delta():
    # Нажали в (10,10) и сдвинули мышь на (30,20) => выделение сдвинулось на (30,20).
    result = _drag(QRect(0, 0, 200, 100), QPoint(10, 10), QPoint(30, 20))
    assert result.topLeft() == QPoint(30, 20)
    # QRect.bottomRight() — это включительная последняя пиксельная координата
    # (x + width - 1), поэтому (229, 119), а не (230, 120).
    assert result.bottomRight() == QPoint(229, 119)
    assert result.size() == QSize(200, 100)


def test_pan_preserves_size():
    original = QRect(0, 0, 200, 100)
    result = _drag(original, QPoint(10, 10), QPoint(30, 20))
    assert result.size() == original.size() == QSize(200, 100)


def test_pan_zero_delta_returns_equal_rect():
    rect = QRect(5, 5, 100, 50)
    # Мышь не сдвинулась относительно точки нажатия.
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
    # Реальный drag = press, затем несколько mouse-move, каждый раз с уже
    # сдвинутым selection_rect. Размер должен оставаться стабильным на каждом
    # шаге, а позиция — зависеть только от сдвига от точки нажатия, а не от
    # числа шагов (иначе перемещение «накапливается»/ускоряется).
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
    # Регрессионный тест на «ускорение»/накопительный эффект.
    #
    # Ключевое ожидание: перемещение выделения за ОДИН ход в конечную точку
    # должно совпадать с серией ходов, завершающихся в той же точке. Если
    # дельта накапливается (каждый ход сдвигает и так сдвинутый rect на
    # вектор до точки нажатия), серия уводит rect дальше, чем одиночный ход —
    # это и есть наблюдаемое «ускорение» выделения за мышью.
    final_delta = QPoint(60, 45)
    original = QRect(0, 0, 200, 100)

    # Один ход прямо в конечную точку.
    single = _drag(original, QPoint(0, 0), final_delta)
    assert single.topLeft() == final_delta

    # Серия ходов, последовательно проходящая через разные точки и
    # завершающаяся в той же final_delta.
    strat = PanStrategy()
    strat.on_mouse_press(QPoint(0, 0), original)
    r = strat.on_mouse_move(QPoint(10, 10))
    r = strat.on_mouse_move(QPoint(25, 40))
    r = strat.on_mouse_move(final_delta)

    # Размер при перемещении не меняется…
    assert r.size() == original.size() == QSize(200, 100)
    # …и результат не зависит от числа промежуточных шагов: серия == один ход.
    assert r == single
