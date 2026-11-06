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

from barbaros.widgets.image_crop.policy import (
    BoundaryPolicy,
    CropPolicy,
    MinSizePolicy,
    PanBoundaryPolicy,
)
from barbaros.widgets.image_crop.transform_strategy import (
    CornerStrategy,
    CreateStrategy,
    HandlePos,
    PanStrategy,
    SideStrategy,
)

# Selection frame geometry
DEFAULT_HIT_BORDER = 40
MIN_HIT_BORDER = 3
HIT_BORDER_THRESHOLD = DEFAULT_HIT_BORDER * 3  # 120
MASK_ALPHA = 128  # 0.5 * 255

SIDE_TOP = 1
SIDE_RIGHT = 2
SIDE_BOTTOM = 4
SIDE_LEFT = 8

# Which inner sides of the zone are highlighted (event_area_paint in Pix).
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
    """C-style round(): halves are rounded away from zero. Needed for signed
    deltas: otherwise +0.5 and -0.5 would give results of different magnitude.
    The handle would then jump in one direction only.
    """
    if value >= 0:
        return floor(value + 0.5)
    return -floor(-value + 0.5)


def point_in_zone(x: float, y: float, zone: tuple[int, int, int, int]) -> bool:
    """point_in_rectangle from Pix: the right/bottom edge is inclusive."""
    zx, zy, zw, zh = zone
    return zx <= x <= zx + zw and zy <= y <= zy + zh


def hit_border(selection_w: int, selection_h: int) -> int:
    """Size of the invisible handle zone in selector pixels."""
    border = DEFAULT_HIT_BORDER
    if selection_w < HIT_BORDER_THRESHOLD:
        border = selection_w // 3
    if selection_h < HIT_BORDER_THRESHOLD:  # in Pix the second condition overrides the first
        border = selection_h // 3
    return max(border, MIN_HIT_BORDER)


def handle_zones(sx: int, sy: int, sw: int, sh: int):
    """Hit-test zones in priority order (same as get_event_area_from_position in Pix)."""
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
    """Hover bracket segments along the inner border of the zone."""
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


class CropSelection(QWidget):
    """Crop widget: selection framing in the style of [Pix](https://github.com/linuxmint/pix).

    Accepts a QImage, fits it into the widget and supports zoom.
    Painting follows the Pix implementation. Selection coordinates are stored
    in image pixels and converted to widget coordinates when painting
    and hit-testing. Selection changes are driven by strategies and policies;
    drags are computed relative to the press point (like dragStart/dragStartSel in Pix).
    """

    zoomChanged = Signal(float)

    ZOOM_MIN = 0.1
    ZOOM_MAX = 8.0
    ZOOM_FACTOR = 1.01

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
        # Zone under the cursor with no button held (for the hover bracket and cursor).
        self.hovered_handle: HandlePos = HandlePos.NONE
        # Press point in widget coordinates. Mouse delta during a drag is computed
        # from it: the absolute cursor position is not used, otherwise the handle
        # would "jump" to the cursor at the moment of press (the handle zone is up to 40 px).
        self.press_widget_pos = QPoint()
        # Active drag flag (mouse button held). Splits mouseMoveEvent into two
        # modes: with no button held — only the cursor changes (hover), with the
        # button held — actual resize/pan of the selection. Without it, mouse
        # movement over the widget would trigger selection changes.
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

        # List of active policies: minimum size first, then boundaries
        # (boundaries are applied last — they finally clip the selection).
        self.policies: list[CropPolicy] = [
            MinSizePolicy(50, 50),
            BoundaryPolicy(),
        ]
        # Panning has its own boundary rule: moving the selection against an
        # image edge must translate it, not clip (and so shrink) it.
        self.pan_policies: list[CropPolicy] = [
            PanBoundaryPolicy(),
        ]

        # Zoom state.
        self.zoom_level: float = 1.0
        self.fit_scale: float = 1.0
        self.scale_factor: float = 1.0
        self.display_rect: QRect | None = None
        self.image_offset: QPoint | None = None

        # Zoom anchor correction: (point in viewport coordinates, image point
        # under it) that must stay under the cursor after the widget is resized.
        self._pending_zoom_anchor: tuple[QPointF, QPointF] | None = None
        # Owned by the widget, so a pending correction dies with it instead of
        # firing into a deleted dialog.
        self._zoom_anchor_timer = QTimer(self)
        self._zoom_anchor_timer.setSingleShot(True)
        self._zoom_anchor_timer.setInterval(0)
        self._zoom_anchor_timer.timeout.connect(self._apply_pending_zoom_anchor)

        self._update_layout()

    def update_fit_scale(self, view_w: int, view_h: int):
        """Computes the base scale for fitting the image into the given area."""
        if self.image.isNull():
            return

        iw, ih = self.image.width(), self.image.height()
        if iw <= 0 or ih <= 0:
            return

        self.fit_scale = min(view_w / iw, view_h / ih)
        # After the base scale changes, the widget size must be updated
        self._update_layout()
        # Widget geometry changed — reset hover so the bracket does not "stick".
        self.hovered_handle = HandlePos.NONE
        self.update()

    def _update_layout(self):
        """Sets the widget size based on the current zoom and fit_scale."""
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
        """Converts widget coordinates to image coordinates."""
        if self.scale_factor == 0:
            return widget_point

        return QPoint(
            int(widget_point.x() / self.scale_factor),
            int(widget_point.y() / self.scale_factor),
        )

    def _to_image_delta(self, widget_delta: QPoint) -> QPoint:
        """Widget-coordinate delta -> delta in image pixels.

        The delta itself is rounded, not two absolute positions: otherwise at a
        fractional scale the difference of two roundings gives a different step
        in the positive and in the negative direction.
        """
        if self.scale_factor == 0:
            return widget_delta

        return QPoint(
            round_half_away_from_zero(widget_delta.x() / self.scale_factor),
            round_half_away_from_zero(widget_delta.y() / self.scale_factor),
        )

    def _apply_policies(self, rect: QRect, policies: list[CropPolicy]) -> QRect:
        for policy in policies:
            rect = policy.apply(rect, self.image.size())
        return rect

    def _selection_screen_rect(self) -> QRect:
        """Selection in image pixels -> rectangle in widget coordinates."""
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

        # 1. Dimming outside the selection; it is absent during a drag.
        if not self.is_selecting:
            painter.fillRect(image_rect, QColor(0, 0, 0, MASK_ALPHA))
            painter.save()
            painter.setClipRect(disp.intersected(image_rect))
            painter.drawPixmap(image_rect, self.pixmap)
            painter.restore()

        # 2. Frame and hover bracket — Difference, 1 logical px.
        highlight = self.active_handle if self.is_selecting else self.hovered_handle
        zones = dict(self._handle_zones())

        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Difference)
        painter.setClipRect(
            QRect(disp.x(), disp.y(), disp.width() + 1, disp.height() + 1)
        )
        pen = QPen(QColor(255, 255, 255))
        # 1 logical px: on HiDPI Qt scales the line itself to a whole number of
        # device px, so it stays crisp. Dividing by devicePixelRatio produced a
        # subpixel "hairline" that antialiasing blurred into a smear.
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
        """Returns the zone under a widget point (or HandlePos.NONE)."""
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
            # Create a new selection from the current point. Policies are
            # applied here too: a click without a drag leaves a 1x1 rect,
            # which would be cropped and sent to OCR.
            bounds = QRect(0, 0, self.image.width(), self.image.height())
            new_rect = QRect(img_pos, img_pos).normalized().intersected(bounds)
            self.selection_rect = self._apply_policies(new_rect, self.policies)

        # The strategy records the press point and the selection at the moment of press.
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

        # 1. The strategy computes the "desired" result: the selection at the moment
        #    of press, changed by the mouse delta. The absolute cursor position is
        #    not used — otherwise the handle jumps to the cursor.
        strategy = self.strategies[self.active_handle]
        proposed_rect = strategy.on_mouse_move(img_delta).normalized()

        # 2. Policies filter and correct the result. Panning uses its own
        #    boundary rule, otherwise clipping would shrink the selection.
        policies = (
            self.pan_policies
            if self.active_handle == HandlePos.INSIDE
            else self.policies
        )
        self.selection_rect = self._apply_policies(proposed_rect, policies)
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
        """Mouse wheel: zoom around the cursor. Panning is done via the scrollbars."""
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return

        factor = self.ZOOM_FACTOR if delta > 0 else 1 / self.ZOOM_FACTOR
        self.set_zoom_at(event.position(), self.zoom_level * factor)
        event.accept()

    # --- Public API ---

    def get_crop_rect(self) -> QRect | None:
        """Current crop area in image coordinates."""
        return self.selection_rect

    def set_crop_rect(self, rect: QRect | None):
        """Sets the initial crop area (in image coordinates)."""
        self.selection_rect = rect
        # Selection changed — reset hover so the bracket does not "stick".
        self.hovered_handle = HandlePos.NONE
        self.update()

    def set_zoom(self, zoom: float):
        """Set the zoom level (1.0 = fitted to the widget)."""
        zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        if zoom == self.zoom_level:
            return

        self.zoom_level = zoom
        self._update_layout()
        # Zoom changes geometry — reset hover so the bracket does not "stick".
        self.hovered_handle = HandlePos.NONE
        self.zoomChanged.emit(self.zoom_level)
        self.update()

    def set_zoom_at(self, anchor: QPointF, zoom: float):
        """Zooms keeping the image point under `anchor` fixed on screen.

        `anchor` is in widget coordinates. The widget only decides its own size;
        where the image sits inside the viewport is controlled by the enclosing
        QScrollArea, so after the resize the scrollbars are shifted to bring the
        anchor point back under the cursor.
        """
        scroll_area = self._enclosing_scroll_area()
        if scroll_area is None or self.scale_factor == 0:
            self.set_zoom(zoom)
            return

        viewport = scroll_area.viewport()
        # Point on screen and the image point that must stay under it.
        viewport_anchor = QPointF(self.mapTo(viewport, QPoint(0, 0))) + anchor
        image_anchor = QPointF(
            anchor.x() / self.scale_factor, anchor.y() / self.scale_factor
        )

        self.set_zoom(zoom)
        self._scroll_anchor_into_place(scroll_area, viewport_anchor, image_anchor)

        # The scrollbar range depends on whether the scrollbars are visible, and
        # Qt updates the viewport size only on the next layout pass. Until then
        # the shift above may be clipped by a stale maximum (a scrollbar that has
        # just appeared), so it is repeated once the layout has settled.
        self._pending_zoom_anchor = (viewport_anchor, image_anchor)
        self._zoom_anchor_timer.start()

    def _enclosing_scroll_area(self) -> QScrollArea | None:
        """The scroll area that displays this widget, if any."""
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return parent
            parent = parent.parentWidget()
        return None

    def _scroll_anchor_into_place(
        self, scroll_area: QScrollArea, viewport_anchor: QPointF, image_anchor: QPointF
    ):
        """Scrolls the viewport so the image anchor is at the given viewport point."""
        scale = self.scale_factor
        scroll_area.horizontalScrollBar().setValue(
            round_half_away_from_zero(image_anchor.x() * scale - viewport_anchor.x())
        )
        scroll_area.verticalScrollBar().setValue(
            round_half_away_from_zero(image_anchor.y() * scale - viewport_anchor.y())
        )

    def _apply_pending_zoom_anchor(self):
        pending = self._pending_zoom_anchor
        scroll_area = self._enclosing_scroll_area()
        if pending is None or scroll_area is None:
            return

        self._pending_zoom_anchor = None
        self._scroll_anchor_into_place(scroll_area, *pending)


class CropDialog(QDialog):
    """Modal dialog for cropping images with GIMP-like/Pix-like interface"""

    def __init__(
        self, image: QImage, parent=None, initial_crop_rect: QRect | None = None
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Crop Image"))
        self.setModal(True)
        self.resize(800, 600)

        self.original_image = image
        self.crop_widget = CropSelection(image, self)
        initial_crop_rect = initial_crop_rect or QRect(
            0, 0, image.width(), image.height()
        )
        self.crop_widget.set_crop_rect(initial_crop_rect)

        # Wrapper for the scrollbars.
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.crop_widget)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setFrameStyle(QFrame.Shape.StyledPanel)

        # Deferred initial scale calculation so the viewport has time to initialize
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
        self.zoom_slider.setMinimum(int(CropSelection.ZOOM_MIN * 100))
        self.zoom_slider.setMaximum(int(CropSelection.ZOOM_MAX * 100))
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
        # After the window is shown, the viewport gets its real size
        if self.scroll_area and self.crop_widget:
            view_w = self.scroll_area.viewport().width()
            view_h = self.scroll_area.viewport().height()
            self.crop_widget.update_fit_scale(view_w, view_h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Update the base fit scale when the window size changes
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
