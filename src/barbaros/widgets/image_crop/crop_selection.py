from PySide6.QtCore import QPoint, QRect, Qt, Signal, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
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


class GimpStyleCropSelection(QWidget):
    """Виджет обрезки в стиле GIMP с использованием стратегий и политик.

    Принимает QImage, вписывает его в виджет и поддерживает зум.
    Выделение области управляется диспетчеризацией по типу кнопки мыши
    (HandlePos) через соответствующие CropStrategy и фильтруется CropPolicy
    (границы изображения + минимальный размер). Координаты выделения хранятся
    в системе координат изображения; конвертация в координаты виджета
    выполняется при отрисовке и определении кнопок.
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
        self.handle_size = 8
        self.active_handle = HandlePos.NONE
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

        self.handle_map = {
            HandlePos.TOP_LEFT: lambda r, s: QRect(
                r.topLeft().x() - s, r.topLeft().y() - s, 2 * s, 2 * s
            ),
            HandlePos.TOP_RIGHT: lambda r, s: QRect(
                r.topRight().x() - s, r.topRight().y() - s, 2 * s, 2 * s
            ),
            HandlePos.BOTTOM_LEFT: lambda r, s: QRect(
                r.bottomLeft().x() - s, r.bottomLeft().y() - s, 2 * s, 2 * s
            ),
            HandlePos.BOTTOM_RIGHT: lambda r, s: QRect(
                r.bottomRight().x() - s, r.bottomRight().y() - s, 2 * s, 2 * s
            ),
            HandlePos.TOP_CENTER: lambda r, s: QRect(
                r.center().x() - s, r.top() - s, 2 * s, 2 * s
            ),
            HandlePos.BOTTOM_CENTER: lambda r, s: QRect(
                r.center().x() - s, r.bottom() - s, 2 * s, 2 * s
            ),
            HandlePos.LEFT_CENTER: lambda r, s: QRect(
                r.left() - s, r.center().y() - s, 2 * s, 2 * s
            ),
            HandlePos.RIGHT_CENTER: lambda r, s: QRect(
                r.right() - s, r.center().y() - s, 2 * s, 2 * s
            ),
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

    def _to_widget_point(self, img_point: QPoint) -> QPoint:
        """Конвертирует координаты изображения в координаты виджета."""
        return QPoint(
            int(img_point.x() * self.scale_factor),
            int(img_point.y() * self.scale_factor),
        )

    def _to_image_point(self, widget_point: QPoint) -> QPoint:
        """Конвертирует координаты виджета в координаты изображения."""
        if self.scale_factor == 0:
            return widget_point

        return QPoint(
            int(widget_point.x() / self.scale_factor),
            int(widget_point.y() / self.scale_factor),
        )

    def _widget_rect_from_image(self, img_rect: QRect) -> QRect:
        tl = self._to_widget_point(img_rect.topLeft())
        br = self._to_widget_point(img_rect.bottomRight())
        return QRect(tl, br).normalized()

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

        if self.selection_rect is None or self.selection_rect.isNull():
            return

        disp = self._widget_rect_from_image(self.selection_rect)

        overlay_color = QColor(0, 0, 0, 100)
        painter.fillRect(QRect(0, 0, self.width(), disp.top()), overlay_color)
        painter.fillRect(
            QRect(0, disp.bottom(), self.width(), self.height() - disp.bottom()),
            overlay_color,
        )
        painter.fillRect(
            QRect(0, disp.top(), disp.left(), disp.height()), overlay_color
        )
        painter.fillRect(
            QRect(
                disp.right(),
                disp.top(),
                self.width() - disp.right(),
                disp.height(),
            ),
            overlay_color,
        )

        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(disp)

        handle_color = QColor(255, 165, 0)
        painter.setBrush(QBrush(handle_color))
        painter.setPen(QPen(handle_color.darker(115), 1))
        s = self.handle_size
        for h_id, func in self.handle_map.items():
            painter.drawRect(func(disp, s))

    def get_handle_at(self, pos: QPoint) -> HandlePos:
        """Возвращает id кнопки выделения в точке (или HandlePos.NONE)."""
        if self.selection_rect is None or self.selection_rect.isNull():
            return HandlePos.NONE

        img_pos = self._to_image_point(pos)
        s = self.handle_size
        for h_id, func in self.handle_map.items():
            if func(self.selection_rect, s).contains(img_pos):
                return h_id

        if self.selection_rect.contains(img_pos):
            return HandlePos.INSIDE
        return HandlePos.NONE

    def _update_cursor(self, pos: QPoint):
        h: HandlePos = self.get_handle_at(pos)
        cursors = {
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
        self.setCursor(cursors.get(h, Qt.CursorShape.ArrowCursor))

    def mousePressEvent(self, event):
        if self.image.isNull():
            return

        pos = event.position().toPoint()
        img_pos = self._to_image_point(pos)

        self.active_handle = self.get_handle_at(pos)
        self.is_selecting = True

        # Стратегия готовится к перемещению/изменению выделения.
        self.strategies[self.active_handle].on_mouse_press(img_pos, self.selection_rect)

        if self.active_handle == HandlePos.NONE:
            # Создание нового выделения из текущей точки.
            bounds = QRect(0, 0, self.image.width(), self.image.height())
            self.selection_rect = (
                QRect(img_pos, img_pos).normalized().intersected(bounds)
            )

        self.update()

    def mouseMoveEvent(self, event):
        """Handle mouse move events for resizing/moving crop rectangle"""
        pos = event.position().toPoint()

        if not self.is_selecting:
            self._update_cursor(pos)
            return

        img_pos = self._to_image_point(pos)

        # 1. Стратегия рассчитывает «желаемый» результат.
        strategy = self.strategies[self.active_handle]
        proposed_rect = strategy.on_mouse_move(
            self.selection_rect, img_pos
        ).normalized()

        # 2. Политики фильтруют и корректируют результат.
        final_rect = proposed_rect
        for policy in self.policies:
            final_rect = policy.apply(final_rect, self.image.size())

        self.selection_rect = final_rect
        self.update()

    def mouseReleaseEvent(self, event):
        self.is_selecting = False
        self.active_handle = HandlePos.NONE
        self.update()

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
        self.update()

    def set_zoom(self, zoom: float):
        """Установить уровень зума (1.0 = вписано в виджет)."""
        zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        if zoom != self.zoom_level:
            self.zoom_level = zoom
            self._update_layout()
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
        # TODO: translate
        QMessageBox.information(
            self,
            self.tr("Crop Controls"),
            "<table>"
            "<tr><td><b>Action</b></td><td><b>Control</b></td></tr>"
            "<tr><td>Zoom in/out</td><td>Scroll Wheel</td></tr>"
            "<tr><td>Resize crop area</td><td>Drag crop handles</td></tr>"
            "<tr><td>Move crop area</td><td>Drag inside crop</td></tr>"
            "<tr><td>Create new crop</td><td>Click outside crop</td></tr>"
            "<tr><td>Zoom in/out</td><td>- / + buttons</td></tr>"
            "<tr><td>Set zoom level</td><td>Slider</td></tr>"
            "<tr><td>Fit image to window</td><td>Reset</td></tr>"
            "</table>",
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
