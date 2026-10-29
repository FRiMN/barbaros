from math import floor

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from barbaros.widgets.image_crop.policy import BoundaryPolicy, MinSizePolicy
from barbaros.widgets.image_crop.transform_strategy import (
    CornerStrategy,
    CreateStrategy,
    HandlePos,
    PanStrategy,
    SideStrategy,
)

# Геометрия рамки выделения — docs/specs/pix-crop-selector/constants.yaml.
DEFAULT_HIT_BORDER = 40
MIN_HIT_BORDER = 3
HIT_BORDER_THRESHOLD = DEFAULT_HIT_BORDER * 3  # 120
MASK_ALPHA = 128  # 0.5 * 255

SIDE_TOP = 1
SIDE_RIGHT = 2
SIDE_BOTTOM = 4
SIDE_LEFT = 8

# Какие внутренние стороны зоны подсвечиваются (event_area_paint в Pix).
BRACKET_SIDES = {
    HandlePos.TOP_CENTER: SIDE_RIGHT | SIDE_BOTTOM | SIDE_LEFT,
    HandlePos.BOTTOM_CENTER: SIDE_TOP | SIDE_RIGHT | SIDE_LEFT,
    HandlePos.LEFT_CENTER: SIDE_TOP | SIDE_RIGHT | SIDE_BOTTOM,
    HandlePos.RIGHT_CENTER: SIDE_TOP | SIDE_BOTTOM | SIDE_LEFT,
    HandlePos.TOP_LEFT: SIDE_RIGHT | SIDE_BOTTOM,
    HandlePos.TOP_RIGHT: SIDE_BOTTOM | SIDE_LEFT,
    HandlePos.BOTTOM_LEFT: SIDE_TOP | SIDE_RIGHT,
    HandlePos.BOTTOM_RIGHT: SIDE_TOP | SIDE_LEFT,
}

CURSOR_BY_HANDLE = {
    HandlePos.TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
    HandlePos.BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
    HandlePos.TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
    HandlePos.BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
    HandlePos.TOP_CENTER: Qt.CursorShape.SizeVerCursor,
    HandlePos.BOTTOM_CENTER: Qt.CursorShape.SizeVerCursor,
    HandlePos.LEFT_CENTER: Qt.CursorShape.SizeHorCursor,
    HandlePos.RIGHT_CENTER: Qt.CursorShape.SizeHorCursor,
    HandlePos.INSIDE: Qt.CursorShape.SizeAllCursor,
}


def round_half_away_from_zero(value: float) -> int:
    """round() из C: половина округляется от нуля. Нужно для сдвигов, у которых
    есть знак: иначе +0.5 и -0.5 давали бы разный по модулю результат и ручка
    дёргалась бы только в одну сторону.
    """
    if value >= 0:
        return floor(value + 0.5)
    return -floor(-value + 0.5)


def point_in_zone(x: float, y: float, zone: tuple[int, int, int, int]) -> bool:
    """point_in_rectangle из Pix: правая/нижняя граница включительно."""
    zx, zy, zw, zh = zone
    return zx <= x <= zx + zw and zy <= y <= zy + zh


def hit_border(selection_w: int, selection_h: int) -> int:
    """Размер невидимой зоны ручки в selector-пикселях."""
    border = DEFAULT_HIT_BORDER
    if selection_w < HIT_BORDER_THRESHOLD:
        border = selection_w // 3
    if selection_h < HIT_BORDER_THRESHOLD:  # в Pix второе условие перекрывает первое
        border = selection_h // 3
    return max(border, MIN_HIT_BORDER)


def handle_zones(sx: int, sy: int, sw: int, sh: int):
    """Зоны хит-теста в порядке приоритета (как get_event_area_from_position в Pix)."""
    border = hit_border(sw, sh)
    x, y = sx - 1, sy - 1
    width, height = sw + 1, sh + 1
    b = border
    return [
        (HandlePos.BOTTOM_RIGHT, (x + width - b, y + height - b, b, b)),
        (HandlePos.BOTTOM_LEFT, (x, y + height - b, b, b)),
        (HandlePos.TOP_RIGHT, (x + width - b, y, b, b)),
        (HandlePos.TOP_LEFT, (x, y, b, b)),
        (HandlePos.RIGHT_CENTER, (x + width - b, y + b, b, max(height - 2 * b, 0))),
        (HandlePos.LEFT_CENTER, (x, y + b, b, max(height - 2 * b, 0))),
        (HandlePos.BOTTOM_CENTER, (x + b, y + height - b, max(width - 2 * b, 0), b)),
        (HandlePos.TOP_CENTER, (x + b, y, max(width - 2 * b, 0), b)),
        (HandlePos.INSIDE, (x, y, width, height)),
    ]


def bracket_segments(zone, handle: HandlePos) -> list[tuple[QPointF, QPointF]]:
    """Отрезки hover-скобки по внутренней границе зоны."""
    sides = BRACKET_SIDES.get(handle)
    if sides is None:
        return []
    zx, zy, zw, zh = zone
    x, y = zx + 0.5, zy + 0.5
    w, h = zw - 1.0, zh - 1.0
    segments = []
    if sides & SIDE_TOP:
        segments.append((QPointF(x, y), QPointF(x + w, y)))
    if sides & SIDE_RIGHT:
        segments.append((QPointF(x + w, y), QPointF(x + w, y + h)))
    if sides & SIDE_BOTTOM:
        segments.append((QPointF(x, y + h), QPointF(x + w, y + h)))
    if sides & SIDE_LEFT:
        segments.append((QPointF(x, y), QPointF(x, y + h)))
    return segments


class GimpStyleCropSelection(QWidget):
    """Виджет обрезки: рамка выделения в стиле Pix.

    Принимает QImage, вписывает его в виджет и поддерживает зум.
    Отрисовка (затемнение 0.5, рамка 1 логический px в режиме Difference, hover-скобка)
    повторяет docs/specs/pix-crop-selector. Координаты выделения хранятся
    в пикселях изображения, в координаты виджета пересчитываются при отрисовке
    и hit-test. Изменение выделения управляется стратегиями и политиками;
    драг считается относительно точки нажатия (как dragStart/dragStartSel в Pix).
    """

    zoomChanged = Signal(float)

    ZOOM_MIN = 0.1
    ZOOM_MAX = 8.0

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.image = image if image is not None else QImage()
        self.pixmap = (
            QPixmap.fromImage(self.image) if not self.image.isNull() else QPixmap()
        )

        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

        self.selection_rect: QRect | None = None
        self.active_handle = HandlePos.NONE
        # Зона под курсором без зажатой кнопки (для hover-скобки и курсора).
        self.hovered_handle: HandlePos = HandlePos.NONE
        # Точка нажатия в координатах виджета. От неё считается сдвиг мыши при
        # драге: абсолютная позиция курсора не используется, иначе ручка
        # «прыгает» к курсору в момент нажатия (зона ручки — до 40 px).
        self.press_widget_pos = QPoint()
        # Флаг активного перетаскивания (нажата кнопка мыши). Разделяет два
        # режима в mouseMoveEvent: без зажатия — только смена курсора (hover),
        # с зажатием — реальный ресайз/панорамирование выделения. Без него
        # движение мыши над виджетом запускало бы изменение выделения.
        self.is_selecting = False

        self.strategies = {
            HandlePos.TOP_LEFT: CornerStrategy(HandlePos.TOP_LEFT),
            HandlePos.TOP_RIGHT: CornerStrategy(HandlePos.TOP_RIGHT),
            HandlePos.BOTTOM_LEFT: CornerStrategy(HandlePos.BOTTOM_LEFT),
            HandlePos.BOTTOM_RIGHT: CornerStrategy(HandlePos.BOTTOM_RIGHT),
            HandlePos.TOP_CENTER: SideStrategy(HandlePos.TOP_CENTER),
            HandlePos.BOTTOM_CENTER: SideStrategy(HandlePos.BOTTOM_CENTER),
            HandlePos.LEFT_CENTER: SideStrategy(HandlePos.LEFT_CENTER),
            HandlePos.RIGHT_CENTER: SideStrategy(HandlePos.RIGHT_CENTER),
            HandlePos.INSIDE: PanStrategy(),
            HandlePos.NONE: CreateStrategy(),
        }

        # Список активных политик: сначала минимальный размер, затем границы
        # (границы применяются последними — финально обрезают выделение).
        self.policies = [
            MinSizePolicy(50, 50),
            BoundaryPolicy(),
        ]

        # Состояние зума.
        self.zoom_level: float = 1.0
        self.fit_scale: float = 1.0
        self.scale_factor: float = 1.0
        self.display_rect: QRect | None = None
        self.image_offset: QPoint | None = None

        self._update_layout()

    def update_fit_scale(self, view_w: int, view_h: int):
        """Вычисляет базовый масштаб для вписывания изображения в указанную область."""
        if self.image.isNull():
            return

        iw, ih = self.image.width(), self.image.height()
        if iw <= 0 or ih <= 0:
            return

        self.fit_scale = min(view_w / iw, view_h / ih)
        # После изменения базового масштаба нужно обновить размер виджета
        self._update_layout()
        # Геометрия виджета изменилась — сбросить hover, чтобы скобка не «зависла».
        self.hovered_handle = HandlePos.NONE
        self.update()

    def _update_layout(self):
        """Устанавливает размер виджета на основе текущего зума и fit_scale."""
        if self.image.isNull():
            self.scale_factor = 1.0
            return

        iw, ih = self.image.width(), self.image.height()
        self.scale_factor = self.fit_scale * self.zoom_level

        scaled_w = int(iw * self.scale_factor)
        scaled_h = int(ih * self.scale_factor)

        self.display_rect = QRect(0, 0, scaled_w, scaled_h)
        self.image_offset = QPoint(0, 0)
        self.setFixedSize(scaled_w, scaled_h)

    def _to_image_point(self, widget_point: QPoint) -> QPoint:
        """Конвертирует координаты виджета в координаты изображения."""
        if self.scale_factor == 0:
            return widget_point

        return QPoint(
            int(widget_point.x() / self.scale_factor),
            int(widget_point.y() / self.scale_factor),
        )

    def _to_image_delta(self, widget_delta: QPoint) -> QPoint:
        """Сдвиг в координатах виджета -> сдвиг в пикселях изображения.

        Округляется именно сдвиг, а не две абсолютные позиции: иначе на нецелом
        масштабе разность двух округлений даёт разный шаг в плюс и в минус.
        """
        if self.scale_factor == 0:
            return widget_delta

        return QPoint(
            round_half_away_from_zero(widget_delta.x() / self.scale_factor),
            round_half_away_from_zero(widget_delta.y() / self.scale_factor),
        )

    def _selection_screen_rect(self) -> QRect:
        """sel в пикселях изображения -> прямоугольник в координатах виджета."""
        rect = self.selection_rect
        scale = self.scale_factor
        return QRect(
            round_half_away_from_zero(rect.x() * scale),
            round_half_away_from_zero(rect.y() * scale),
            round_half_away_from_zero(rect.width() * scale),
            round_half_away_from_zero(rect.height() * scale),
        )

    def _selection_is_empty(self) -> bool:
        rect = self.selection_rect
        return rect is None or rect.width() <= 0 or rect.height() <= 0

    def _handle_zones(self):
        if self._selection_is_empty():
            return []
        disp = self._selection_screen_rect()
        return handle_zones(disp.x(), disp.y(), disp.width(), disp.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.image.isNull():
            painter.fillRect(self.rect(), Qt.GlobalColor.lightGray)
            painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, self.tr("No image loaded")
            )
            return

        painter.drawPixmap(self.display_rect, self.pixmap)

        if self._selection_is_empty():
            return

        disp = self._selection_screen_rect()
        image_rect = self.display_rect

        # 1. Затемнение снаружи выделения; во время драга его нет.
        if not self.is_selecting:
            painter.fillRect(image_rect, QColor(0, 0, 0, MASK_ALPHA))
            painter.save()
            painter.setClipRect(disp.intersected(image_rect))
            painter.drawPixmap(image_rect, self.pixmap)
            painter.restore()

        # 2. Рамка и hover-скобка — Difference, 1 логический px.
        highlight = self.active_handle if self.is_selecting else self.hovered_handle
        zones = dict(self._handle_zones())

        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)
        painter.setClipRect(
            QRect(disp.x(), disp.y(), disp.width() + 1, disp.height() + 1)
        )
        pen = QPen(QColor(255, 255, 255))
        # 1 логический px: на HiDPI Qt сам масштабирует линию до целого числа
        # device px, поэтому она остаётся чёткой. Деление на devicePixelRatio
        # давало субпиксельный «волосок», который антиалиасинг размывал в смесь.
        pen.setWidthF(1.0)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(
            QRectF(
                disp.x() + 0.5,
                disp.y() + 0.5,
                max(disp.width() - 1, 0),
                max(disp.height() - 1, 0),
            )
        )

        if highlight in BRACKET_SIDES and highlight in zones:
            path = QPainterPath()
            for start, end in bracket_segments(zones[highlight], highlight):
                path.moveTo(start)
                path.lineTo(end)
            painter.drawPath(path)

        painter.restore()

    def get_handle_at(self, pos: QPoint) -> HandlePos:
        """Возвращает зону под точкой виджета (или HandlePos.NONE)."""
        for handle, zone in self._handle_zones():
            if point_in_zone(pos.x(), pos.y(), zone):
                return handle
        return HandlePos.NONE

    def _update_cursor(self, pos: QPoint):
        handle = self.get_handle_at(pos)
        self.setCursor(CURSOR_BY_HANDLE.get(handle, Qt.CursorShape.CrossCursor))

    def mousePressEvent(self, event):
        if self.image.isNull():
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        pos = event.position().toPoint()
        img_pos = self._to_image_point(pos)
        self.press_widget_pos = pos

        self.active_handle = self.get_handle_at(pos)
        self.is_selecting = True

        if self.active_handle == HandlePos.NONE:
            # Создание нового выделения из текущей точки.
            bounds = QRect(0, 0, self.image.width(), self.image.height())
            self.selection_rect = (
                QRect(img_pos, img_pos).normalized().intersected(bounds)
            )

        # Стратегия запоминает точку нажатия и выделение на момент нажатия.
        self.strategies[self.active_handle].on_mouse_press(img_pos, self.selection_rect)

        self.update()

    def mouseMoveEvent(self, event):
        """Handle mouse move events for resizing/moving crop rectangle"""
        pos = event.position().toPoint()

        if not self.is_selecting:
            handle = self.get_handle_at(pos)
            if handle != self.hovered_handle:
                self.hovered_handle = handle
                self.update()
            self._update_cursor(pos)
            return

        img_delta = self._to_image_delta(pos - self.press_widget_pos)

        # 1. Стратегия рассчитывает «желаемый» результат: выделение на момент
        #    нажатия, изменённое на сдвиг мыши. Абсолютная позиция курсора не
        #    используется — иначе ручка прыгает к курсору.
        strategy = self.strategies[self.active_handle]
        proposed_rect = strategy.on_mouse_move(img_delta).normalized()

        # 2. Политики фильтруют и корректируют результат.
        final_rect = proposed_rect
        for policy in self.policies:
            final_rect = policy.apply(final_rect, self.image.size())

        self.selection_rect = final_rect
        self.update()

    def mouseReleaseEvent(self, event):
        self.is_selecting = False
        self.active_handle = HandlePos.NONE
        pos = event.position().toPoint()
        self.hovered_handle = self.get_handle_at(pos)
        self._update_cursor(pos)
        self.update()

    def leaveEvent(self, event):
        self.hovered_handle = HandlePos.NONE
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        """Колесо мыши: изменение масштаба (зум). Панорамирование — полосы прокрутки."""
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return

        factor = 1.1 if delta > 0 else 1 / 1.1
        self.set_zoom(self.zoom_level * factor)
        event.accept()

    # --- Публичный API ---

    def get_crop_rect(self) -> QRect | None:
        """Текущая область обрезки в координатах изображения."""
        return self.selection_rect

    def set_crop_rect(self, rect: QRect | None):
        """Устанавливает начальную область обрезки (в координатах изображения)."""
        self.selection_rect = rect
        # Выделение изменилось — сбросить hover, чтобы скобка не «зависла».
        self.hovered_handle = HandlePos.NONE
        self.update()

    def set_zoom(self, zoom: float):
        """Установить уровень зума (1.0 = вписано в виджет)."""
        zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        if zoom != self.zoom_level:
            self.zoom_level = zoom
            self._update_layout()
            # Зум меняет геометрию — сбросить hover, чтобы скобка не «зависла».
            self.hovered_handle = HandlePos.NONE
            self.zoomChanged.emit(self.zoom_level)
            self.update()


class CropDialog(QDialog):
    """Modal dialog for cropping images with GIMP-like interface"""

    def __init__(
        self, image: QImage, parent=None, initial_crop_rect: QRect | None = None
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Crop Image"))
        self.setModal(True)
        self.resize(800, 600)

        self.original_image = image
        self.crop_widget = GimpStyleCropSelection(image, self)
        initial_crop_rect = initial_crop_rect or QRect(
            0, 0, image.width(), image.height()
        )
        self.crop_widget.set_crop_rect(initial_crop_rect)

        # Обёртка для полос прокрутки.
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.crop_widget)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setFrameStyle(
            QFrame.Shape.NoFrame | QFrame.Shape.StyledPanel
        )

        # Отложенный расчет начального масштаба, чтобы вьюпорт успел инициализироваться
        QTimer.singleShot(0, self._initial_fit)

        layout = QVBoxLayout()
        layout.addWidget(self.scroll_area)
        layout.addLayout(self._build_zoom_bar())
        self.setLayout(layout)

        self.final_crop_rect: QRect | None = None

    def _build_zoom_bar(self) -> QHBoxLayout:
        zoom_layout = QHBoxLayout()

        btn_minus = QPushButton("-")
        btn_minus.setFixedWidth(32)
        btn_minus.clicked.connect(self._zoom_out)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setMinimum(int(GimpStyleCropSelection.ZOOM_MIN * 100))
        self.zoom_slider.setMaximum(int(GimpStyleCropSelection.ZOOM_MAX * 100))
        self.zoom_slider.setValue(100)
        self.zoom_slider.setTickPosition(QSlider.TickPosition.NoTicks)
        self.zoom_slider.valueChanged.connect(self._on_slider_changed)

        btn_plus = QPushButton("+")
        btn_plus.setFixedWidth(32)
        btn_plus.clicked.connect(self._zoom_in)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setFixedWidth(50)
        self.zoom_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )

        btn_reset = QPushButton(self.tr("Reset"))
        btn_reset.setFixedWidth(50)
        btn_reset.clicked.connect(self._zoom_reset)

        self.crop_widget.zoomChanged.connect(self._on_zoom_changed)

        btn_help = QPushButton("?")
        btn_help.setFixedWidth(32)
        btn_help.clicked.connect(self._show_help)

        zoom_layout.addWidget(btn_minus)
        zoom_layout.addWidget(self.zoom_slider)
        zoom_layout.addWidget(btn_plus)
        zoom_layout.addWidget(self.zoom_label)
        zoom_layout.addWidget(btn_reset)
        zoom_layout.addWidget(btn_help)

        return zoom_layout

    def _on_slider_changed(self, value: int):
        self.crop_widget.set_zoom(value / 100.0)

    def _on_zoom_changed(self, zoom: float):
        pct = int(zoom * 100)
        self.zoom_label.setText(f"{pct}%")
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(pct)
        self.zoom_slider.blockSignals(False)
        self.scroll_area.updateGeometry()

    def _initial_fit(self):
        if self.scroll_area and self.crop_widget:
            view_w = self.scroll_area.viewport().width()
            view_h = self.scroll_area.viewport().height()
            self.crop_widget.update_fit_scale(view_w, view_h)

    def showEvent(self, event):
        super().showEvent(event)
        # После показа окна вьюпорт получает реальный размер
        if self.scroll_area and self.crop_widget:
            view_w = self.scroll_area.viewport().width()
            view_h = self.scroll_area.viewport().height()
            self.crop_widget.update_fit_scale(view_w, view_h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Обновляем базовый масштаб вписывания при изменении размера окна
        if self.scroll_area and self.crop_widget:
            view_w = self.scroll_area.viewport().width()
            view_h = self.scroll_area.viewport().height()
            self.crop_widget.update_fit_scale(view_w, view_h)

    def _zoom_in(self):
        new_zoom = self.crop_widget.zoom_level * 1.25
        self.crop_widget.set_zoom(new_zoom)

    def _zoom_out(self):
        new_zoom = self.crop_widget.zoom_level / 1.25
        self.crop_widget.set_zoom(new_zoom)

    def _zoom_reset(self):
        self.crop_widget.set_zoom(1.0)

    def _show_help(self):
        QMessageBox.information(
            self,
            self.tr("Crop Controls"),
            self.tr(
                "<table>"
                "<tr><td><b>Action</b></td><td><b>Control</b></td></tr>"
                "<tr><td>Zoom in/out</td><td>Scroll Wheel</td></tr>"
                "<tr><td>Resize crop area</td><td>Drag crop handles</td></tr>"
                "<tr><td>Move crop area</td><td>Drag inside crop</td></tr>"
                "<tr><td>Create new crop</td><td>Click outside crop</td></tr>"
                "<tr><td>Zoom in/out</td><td>- / + buttons</td></tr>"
                "<tr><td>Set zoom level</td><td>Slider</td></tr>"
                "<tr><td>Fit image to window</td><td>Reset</td></tr>"
                "</table>"
            ),
        )

    def get_cropped_image(self) -> QImage | None:
        """Return the cropped image based on the final crop rectangle"""
        if self.final_crop_rect is None or self.original_image.isNull():
            return None

        rect = self.final_crop_rect.intersected(
            QRect(0, 0, self.original_image.width(), self.original_image.height())
        )
        if rect.isEmpty():
            return None

        return self.original_image.copy(rect)

    def get_crop_rect(self) -> QRect | None:
        """Return the final crop rectangle"""
        return self.final_crop_rect

    def closeEvent(self, event):
        """Handle dialog close event - treat as accepting the crop"""
        self.final_crop_rect = self.crop_widget.get_crop_rect()
        self.accept()
