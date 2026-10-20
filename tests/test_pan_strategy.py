"""Тесты для PanStrategy из barbaros.widgets.image_crop.transform_strategy.

PanStrategy — это стратегия «ператащить выделение» (drag-to-pan): при движении
мышь всё выделение сдвигается на тот же вектор, не меняя своего размера.
Размер стабильный не только при одиночном ходу из состояния нажатия, но и при
цепочке mouse-move — дельта считается из точки нажатия и применяется к
прямоугольнику на нажатии (rect_on_press), поэтому перемещение не
накапливается за серию ходов (см. test_pan_multiple_moves_preserve_size и
test_pan_no_accumulation_single_move_equals_sequence).
"""
import pytest
from PySide6.QtCore import QRect, QPoint, QSize

from barbaros.widgets.image_crop.transform_strategy import PanStrategy


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    """QApplication нужен не для этих тестов, но снимает вопросы у Qt."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _press_move(drag_start, rect, pos):
    """Симулируем полный цикл: нажали -> передвинули мышь."""
    strat = PanStrategy()
    strat.on_mouse_press(drag_start, rect)
    return strat.on_mouse_move(rect, pos)


def test_pan_translates_by_mouse_delta():
    # Нажали в (10,10), мышь ушла в (40,30) => вектор сдвига (30,20).
    result = _press_move(QPoint(10, 10), QRect(0, 0, 200, 100), QPoint(40, 30))
    assert result.topLeft() == QPoint(30, 20)
    # QRect.bottomRight() — это включительная последняя пиксельная координата
    # (x + width - 1), поэтому (229, 119), а не (230, 120).
    assert result.bottomRight() == QPoint(229, 119)
    assert result.size() == QSize(200, 100)


def test_pan_preserves_size():
    original = QRect(0, 0, 200, 100)
    result = _press_move(QPoint(10, 10), original, QPoint(40, 30))
    assert result.size() == original.size() == QSize(200, 100)


def test_pan_zero_delta_returns_equal_rect():
    rect = QRect(5, 5, 100, 50)
    # Мышь не сдвинулась относительно точки нажатия.
    result = _press_move(QPoint(50, 50), rect, QPoint(50, 50))
    assert result == rect


def test_pan_negative_delta_moves_up_left():
    result = _press_move(QPoint(100, 100), QRect(50, 50, 200, 100), QPoint(80, 90))
    assert result.topLeft() == QPoint(30, 40)
    assert result.size() == QSize(200, 100)


def test_pan_press_stores_anchor_state():
    strat = PanStrategy()
    rect = QRect(50, 50, 200, 100)
    strat.on_mouse_press(QPoint(120, 80), rect)
    assert strat.drag_start == QPoint(120, 80)


def test_pan_multiple_moves_preserve_size():
    # Реальный drag = press, затем несколько mouse-move, каждый раз с уже
    # сдвинутым selection_rect. Размер должен оставаться стабильным на каждом
    # шаге, а позиция — зависеть только от конечной точки мыши, а не от числа
    # шагов (иначе перемещение «накапливается»/ускоряется). Дельта считается из
    # точки нажатия (drag_start) и применяется к прямоугольнику, запомненному
    # на нажатии (rect_on_press), а не к уже сдвинутому текущему rect.
    strat = PanStrategy()
    rect = QRect(0, 0, 200, 100)
    strat.on_mouse_press(QPoint(0, 0), rect)

    step1 = strat.on_mouse_move(rect, QPoint(10, 10))
    assert step1.topLeft() == QPoint(10, 10)
    assert step1.size() == QSize(200, 100)

    step2 = strat.on_mouse_move(step1, QPoint(25, 40))
    assert step2.topLeft() == QPoint(25, 40)
    assert step2.size() == QSize(200, 100)

    step3 = strat.on_mouse_move(step2, QPoint(5, 5))
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
    final_pos = QPoint(60, 45)
    original = QRect(0, 0, 200, 100)

    # Один ход прямо в конечную точку.
    single = _press_move(QPoint(0, 0), original, final_pos)
    assert single.topLeft() == final_pos

    # Серия ходов, последовательно проходящая через разные точки и
    # завершающаяся в той же final_pos.
    strat = PanStrategy()
    strat.on_mouse_press(QPoint(0, 0), original)
    r = strat.on_mouse_move(original, QPoint(10, 10))
    r = strat.on_mouse_move(r, QPoint(25, 40))
    r = strat.on_mouse_move(r, final_pos)

    # Размер при перемещении не меняется…
    assert r.size() == original.size() == QSize(200, 100)
    # …и результат не зависит от числа промежуточных шагов: серия == один ход.
    assert r == single
