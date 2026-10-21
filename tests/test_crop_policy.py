"""Тесты для policy: BoundaryPolicy и MinSizePolicy."""
import pytest
from PySide6.QtCore import QRect, QSize

from barbaros.widgets.image_crop.policy import (
    BoundaryPolicy,
    CropPolicy,
    MinSizePolicy,
)


@pytest.fixture(autouse=True, scope="session")
def _qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------- CropPolicy (ABC) ----------


def test_crop_policy_is_abstract():
    """CropPolicy нельзя инстанциировать напрямую — это ABC."""
    with pytest.raises(TypeError):
        CropPolicy()  # noqa: B018


# ---------- BoundaryPolicy ----------

BOUNDARY = BoundaryPolicy()


@pytest.mark.parametrize(
    "rect, img_size, expected",
    [
        # Полностью внутри — без изменений
        (QRect(20, 20, 30, 30), QSize(100, 100), QRect(20, 20, 30, 30)),
        # ЛЕВАЯ выходит за 0: rect(-10,20,40,30) → left=-10,right=30
        (QRect(-10, 20, 40, 30), QSize(100, 100), QRect(0, 20, 30, 30)),
        # ВЕРХняя выходит за 0: rect(20,-10,30,40) → top=-10,bot=29
        (QRect(20, -10, 30, 40), QSize(100, 100), QRect(20, 0, 30, 30)),
        # ПРАВАЯ выходит за width: rect(70,20,50,30) → right=119
        (QRect(70, 20, 50, 30), QSize(100, 100), QRect(70, 20, 30, 30)),
        # НИЖНЯЯ выходит за height: rect(20,70,30,50) → bottom=119
        (QRect(20, 70, 30, 50), QSize(100, 100), QRect(20, 70, 30, 30)),
        # Все четыре стороны выходят за границы
        (QRect(-20, -20, 150, 150), QSize(100, 100), QRect(0, 0, 100, 100)),
    ],
)
def test_boundary_clamps(rect, img_size, expected):
    result = BOUNDARY.apply(rect, img_size)
    assert result == expected


def test_boundary_rect_completely_outside():
    """Полностью вне изображения → intersected возвращает пустой QRect."""
    result = BOUNDARY.apply(QRect(200, 200, 50, 50), QSize(100, 100))
    assert result.isEmpty()


def test_boundary_rect_zero_size_inside():
    result = BOUNDARY.apply(QRect(50, 50, 0, 0), QSize(100, 100))
    assert result.width() == 0
    assert result.height() == 0


def test_boundary_image_size_zero():
    """Пустое изображение — любой rect обрезается в пустой."""
    result = BOUNDARY.apply(QRect(0, 0, 50, 50), QSize(0, 0))
    assert result.isEmpty()


# ---------- MinSizePolicy ----------

IMG_100 = QSize(100, 100)
IMG_200 = QSize(200, 200)


class TestMinSizeDefault:
    """min_w=50, min_h=50 (по умолчанию).

    MinSizePolicy нормализует rect, затем расширяет ширину/высоту, если они
    меньше минимума. Расширение идёт: new_right = min(max_w, rect.right() + extra),
    new_left = max(0, new_right - min_w). max_w берётся как image_size.width(),
    а не width()-1 — это известное ограничение: при расширении слева или
    сверху результат может быть на 1 меньше min (см. test_min_at_left_edge_gaps).
    """

    @pytest.fixture
    def policy(self):
        return MinSizePolicy()

    def test_expands_width_and_height(self, policy):
        # rect(30,30,10,10): w=10<50, h=10<50
        # width: extra=40, new_right=min(100,39+40)=79, new_left=79-50=29, w=50
        # height: extra=40, new_bottom=min(100,39+40)=79, new_top=79-50=29, h=50
        result = policy.apply(QRect(30, 30, 10, 10), IMG_100)
        assert result.width() == 50
        assert result.height() == 50
        assert result.x() == 29
        assert result.y() == 29

    def test_already_satisfied(self, policy):
        result = policy.apply(QRect(10, 10, 60, 60), IMG_100)
        assert result.width() == 60
        assert result.height() == 60

    def test_normalizes_negative_rect(self, policy):
        """QRect(50,50,-10,-10).normalized() → QRect(40,40,10,10)."""
        neg = QRect(50, 50, -10, -10)
        result = policy.apply(neg, IMG_100)
        assert result.width() == 50
        assert result.height() == 50

    def test_at_right_edge_cannot_expand_right(self, policy):
        # rect(90,90,10,10): right=99, max_w=100, extra=40
        # new_right=min(100,99+40)=100, new_left=100-50=50, w=50
        result = policy.apply(QRect(90, 90, 10, 10), IMG_100)
        assert result.width() == 50
        assert result.height() == 50
        assert result.x() == 50
        assert result.right() == 99

    def test_at_left_edge_gaps_off_by_one(self, policy):
        # rect(0,0,10,10): right=9, extra=40, new_right=min(100,9+40)=49
        # new_left=max(0,49-50)=0, w=49 (не 50 — из-за max_w=image_width vs right coord)
        result = policy.apply(QRect(0, 0, 10, 10), IMG_100)
        assert result.width() == 49
        assert result.height() == 49
        assert result.x() == 0
        assert result.y() == 0

    def test_left_edge_expands_when_more_space(self, policy):
        # rect(0,0,50,50): already >= 50x50, no expansion
        result = policy.apply(QRect(0, 0, 50, 50), IMG_100)
        assert result.width() == 50
        assert result.height() == 50

    def test_expands_only_width(self, policy):
        # rect(0,0,10,60): w=10<50, h=60>=50 → только ширина
        result = policy.apply(QRect(0, 0, 10, 60), IMG_100)
        assert result.width() == 49  # see gap logic above
        assert result.height() == 60

    def test_expands_only_height(self, policy):
        result = policy.apply(QRect(0, 0, 60, 10), IMG_100)
        assert result.width() == 60
        assert result.height() == 49


class TestMinSizeCustom:
    @pytest.fixture
    def policy(self):
        return MinSizePolicy(min_w=200, min_h=200)

    def test_cannot_expand_beyond_smaller_image(self, policy):
        result = policy.apply(QRect(0, 0, 10, 10), QSize(100, 100))
        # max_w=100, rect.right()=9, extra=190, new_right=min(100,199)=100
        # new_left=100-200=-100→0, w=100
        assert result.width() == 100
        assert result.height() == 100

    def test_at_left_edge_expands_right(self, policy):
        # rect(0,0,10,10) inside 200x200: right=9, extra=190
        # new_right=min(200,9+190)=199, new_left=max(0,199-200)=0, w=199
        result = policy.apply(QRect(0, 0, 10, 10), IMG_200)
        assert result.width() == 199
        assert result.height() == 199
        assert result.x() == 0
        assert result.y() == 0

    def test_at_right_edge_expands_left(self, policy):
        # rect(190,0,10,10): right=199, extra=190, new_right=min(200,389)=200
        # new_left=200-200=0, w=200
        # height: bottom=9, extra=190, new_bottom=min(200,199)=199 → h=199
        result = policy.apply(QRect(190, 0, 10, 10), IMG_200)
        assert result.x() == 0
        assert result.width() == 200
        assert result.height() == 199

    def test_bottom_edge_expands_up(self, policy):
        result = policy.apply(QRect(0, 190, 10, 10), IMG_200)
        assert result.y() == 0
        assert result.height() == 200


class TestMinSizeBoundary:
    """MinSizePolicy не выходит за границы изображения (в сторону увеличения)."""

    @pytest.fixture
    def policy(self):
        return MinSizePolicy(min_w=100, min_h=100)

    def test_rect_in_middle_of_small_image(self, policy):
        # 50x50 image, min=100 → clamp
        result = policy.apply(QRect(40, 40, 10, 10), QSize(50, 50))
        assert result.width() <= 50
        assert result.height() <= 50

    def test_rect_already_meets_min(self, policy):
        result = policy.apply(QRect(10, 10, 100, 100), IMG_200)
        assert result.width() == 100
        assert result.height() == 100

    def test_rect_near_left_expands_more(self, policy):
        # rect(0,0,10,10) inside 200x200: right=9, extra=90
        # new_right=min(200,9+90)=99, new_left=99-100=-1→0, w=99
        result = policy.apply(QRect(0, 0, 10, 10), IMG_200)
        assert result.width() == 99
        assert result.height() == 99

    def test_expansion_respects_left_boundary(self, policy):
        # new_left = max(0, new_right - min_w), never goes negative
        result = policy.apply(QRect(0, 0, 10, 10), IMG_200)
        assert result.x() >= 0
        assert result.y() >= 0
