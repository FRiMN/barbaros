from PySide6.QtCore import QRect, QPoint, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QBrush
from PySide6.QtWidgets import QWidget


class CropWidget(QWidget):
    """Widget for displaying image and allowing crop rectangle adjustment"""

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.image = image
        self.setMinimumSize(400, 300)

        self.crop_rect: QRect | None = None

        self.dragging_handle: str | None = None
        self.drag_start_pos: QPoint | None = None
        self.drag_start_rect: QRect | None = None

        self.handle_size = 6
        self.handle_hit_radius = 8

        self.setMouseTracking(True)

        self.display_rect: QRect | None = None
        self.image_offset: QPoint | None = None
        self.scale_factor: float = 1.0

    def paintEvent(self, event):
        """Paint the image and crop rectangle with handles"""
        cm = QPainter.CompositionMode

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.image.isNull():
            painter.fillRect(self.rect(), Qt.GlobalColor.lightGray)
            painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "No image loaded"
            )
            return

        widget_rect = self.rect()

        # Calculate scaled size maintaining aspect ratio
        image_width = self.image.width()
        image_height = self.image.height()
        widget_width = widget_rect.width()
        widget_height = widget_rect.height()

        scale = min(widget_width / image_width, widget_height / image_height)
        scaled_width = int(image_width * scale)
        scaled_height = int(image_height * scale)

        x_offset = (widget_width - scaled_width) // 2
        y_offset = (widget_height - scaled_height) // 2

        scaled_rect = QRect(x_offset, y_offset, scaled_width, scaled_height)

        painter.drawImage(scaled_rect, self.image)

        self.display_rect = scaled_rect
        self.image_offset = QPoint(x_offset, y_offset)
        self.scale_factor = scale

        if self.crop_rect is None:
            return

        display_crop_rect = QRect(
            self.image_offset.x() + int(self.crop_rect.x() * self.scale_factor),
            self.image_offset.y() + int(self.crop_rect.y() * self.scale_factor),
            int(self.crop_rect.width() * self.scale_factor),
            int(self.crop_rect.height() * self.scale_factor),
        )

        painter.save()

        # Draw semi-transparent overlay
        overlay_color = QColor(0, 0, 0, 100)
        painter.fillRect(self.rect(), overlay_color)

        # Cut out crop area: redraw image through the crop region
        painter.setClipRect(display_crop_rect, Qt.ClipOperation.IntersectClip)
        painter.drawImage(display_crop_rect, self.image.copy(self.crop_rect))

        painter.restore()

        pen_color = QColor(255, 255, 255)
        painter.setPen(QPen(pen_color, 2))
        painter.drawRect(display_crop_rect)

        self._draw_handles(painter, display_crop_rect)

    def _draw_handles(self, painter: QPainter, rect: QRect):
        """Draw the resize handles on the crop rectangle"""
        handle_color = QColor(255, 165, 0)
        painter.setBrush(QBrush(handle_color))
        painter.setPen(QPen(handle_color, 1))

        hs = self.handle_size

        corners = [
            (rect.left(), rect.top(), "nw"),
            (rect.right() - hs, rect.top(), "ne"),
            (rect.left(), rect.bottom() - hs, "sw"),
            (rect.right() - hs, rect.bottom() - hs, "se"),
        ]

        for x, y, handle_type in corners:
            painter.drawRect(QRect(x, y, hs, hs))

        edges = [
            (rect.center().x() - hs // 2, rect.top(), "n"),
            (rect.right() - hs, rect.center().y() - hs // 2, "e"),
            (rect.center().x() - hs // 2, rect.bottom() - hs, "s"),
            (rect.left(), rect.center().y() - hs // 2, "w"),
        ]

        for x, y, handle_type in edges:
            painter.drawRect(QRect(x, y, hs, hs))

    def get_crop_rect(self) -> QRect | None:
        """Get the current crop rectangle in image coordinates"""
        return self.crop_rect

    def set_crop_rect(self, rect: QRect | None):
        """Set the initial crop rectangle in image coordinates"""
        self.crop_rect = rect
        self.update()

    def mousePressEvent(self, event):
        """Handle mouse press events for resizing/moving crop rectangle"""
        if self.image.isNull():
            return

        pos = event.position().toPoint()

        if self.crop_rect is None:
            image_pos = self._widget_to_image_coords(pos)
            size = 50
            self.crop_rect = QRect(
                image_pos.x() - size // 2, image_pos.y() - size // 2, size, size
            )
            self.crop_rect = self.crop_rect.intersected(
                QRect(0, 0, self.image.width(), self.image.height())
            )
            self.dragging_handle = None
            self.drag_start_pos = pos
            self.drag_start_rect = QRect(self.crop_rect)
            self.update()
            return

        handle_type = self._get_handle_at_position(pos)
        if handle_type:
            self.dragging_handle = handle_type
            self.drag_start_pos = pos
            self.drag_start_rect = QRect(self.crop_rect)
        elif self._is_point_in_crop_rect(pos):
            self.dragging_handle = "move"
            self.drag_start_pos = pos
            self.drag_start_rect = QRect(self.crop_rect)
        else:
            image_pos = self._widget_to_image_coords(pos)
            size = 50
            self.crop_rect = QRect(
                image_pos.x() - size // 2, image_pos.y() - size // 2, size, size
            )
            self.crop_rect = self.crop_rect.intersected(
                QRect(0, 0, self.image.width(), self.image.height())
            )
            self.dragging_handle = None
            self.drag_start_pos = pos
            self.drag_start_rect = QRect(self.crop_rect)

        self.update()

    def mouseMoveEvent(self, event):
        """Handle mouse move events for resizing/moving crop rectangle"""
        pos = event.position().toPoint()

        if (
            self.dragging_handle is None
            or self.drag_start_pos is None
            or self.drag_start_rect is None
        ):
            handle_type = self._get_handle_at_position(pos)
            if handle_type:
                self._set_cursor_for_handle(handle_type)
            elif self._is_point_in_crop_rect(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        delta = pos - self.drag_start_pos

        if self.scale_factor > 0:
            delta_x = int(delta.x() / self.scale_factor)
            delta_y = int(delta.y() / self.scale_factor)
        else:
            delta_x = delta.x()
            delta_y = delta.y()

        new_rect = QRect(self.drag_start_rect)

        if self.dragging_handle == "move":
            new_rect.translate(delta_x, delta_y)
        else:
            if "n" in self.dragging_handle:
                new_rect.setTop(new_rect.top() + delta_y)
            if "s" in self.dragging_handle:
                new_rect.setBottom(new_rect.bottom() + delta_y)
            if "w" in self.dragging_handle:
                new_rect.setLeft(new_rect.left() + delta_x)
            if "e" in self.dragging_handle:
                new_rect.setRight(new_rect.right() + delta_x)

        image_bounds = QRect(0, 0, self.image.width(), self.image.height())
        new_rect = new_rect.intersected(image_bounds)

        if new_rect.width() < 5:
            if "w" in self.dragging_handle:
                new_rect.setLeft(new_rect.right() - 5)
            else:
                new_rect.setRight(new_rect.left() + 5)

        if new_rect.height() < 5:
            if "n" in self.dragging_handle:
                new_rect.setTop(new_rect.bottom() - 5)
            else:
                new_rect.setBottom(new_rect.top() + 5)

        self.crop_rect = new_rect
        self.update()

    def mouseReleaseEvent(self, event):
        """Handle mouse release events"""
        self.dragging_handle = None
        self.drag_start_pos = None
        self.drag_start_rect = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _get_handle_at_position(self, pos: QPoint) -> str | None:
        """Get handle type at the given position, or None if not on a handle"""
        if self.crop_rect is None or self.image.isNull():
            return None

        display_rect = QRect(
            self.image_offset.x() + int(self.crop_rect.x() * self.scale_factor),
            self.image_offset.y() + int(self.crop_rect.y() * self.scale_factor),
            int(self.crop_rect.width() * self.scale_factor),
            int(self.crop_rect.height() * self.scale_factor),
        )

        hs = self.handle_size
        hr = self.handle_hit_radius

        corners = [
            (display_rect.left() - hr // 2, display_rect.top() - hr // 2, "nw"),
            (
                display_rect.right() - hs // 2 - hr // 2,
                display_rect.top() - hr // 2,
                "ne",
            ),
            (
                display_rect.left() - hr // 2,
                display_rect.bottom() - hs // 2 - hr // 2,
                "sw",
            ),
            (
                display_rect.right() - hs // 2 - hr // 2,
                display_rect.bottom() - hs // 2 - hr // 2,
                "se",
            ),
        ]

        for x, y, handle_type in corners:
            if QRect(x, y, hs + hr, hs + hr).contains(pos):
                return handle_type

        edges = [
            (
                display_rect.center().x() - hs // 2 - hr // 2,
                display_rect.top() - hr // 2,
                "n",
            ),
            (
                display_rect.right() - hs // 2 - hr // 2,
                display_rect.center().y() - hs // 2 - hr // 2,
                "e",
            ),
            (
                display_rect.center().x() - hs // 2 - hr // 2,
                display_rect.bottom() - hs // 2 - hr // 2,
                "s",
            ),
            (
                display_rect.left() - hr // 2,
                display_rect.center().y() - hs // 2 - hr // 2,
                "w",
            ),
        ]

        for x, y, handle_type in edges:
            if QRect(x, y, hs + hr, hs + hr).contains(pos):
                return handle_type

        return None

    def _is_point_in_crop_rect(self, pos: QPoint) -> bool:
        """Check if point is inside the crop rectangle (in widget coordinates)"""
        if self.crop_rect is None or self.image.isNull():
            return False

        display_rect = QRect(
            self.image_offset.x() + int(self.crop_rect.x() * self.scale_factor),
            self.image_offset.y() + int(self.crop_rect.y() * self.scale_factor),
            int(self.crop_rect.width() * self.scale_factor),
            int(self.crop_rect.height() * self.scale_factor),
        )

        return display_rect.contains(pos)

    def _set_cursor_for_handle(self, handle_type: str):
        """Set appropriate cursor for the given handle type"""
        if handle_type in ["nw", "se"]:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif handle_type in ["ne", "sw"]:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif handle_type in ["n", "s"]:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif handle_type in ["w", "e"]:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _widget_to_image_coords(self, widget_pos: QPoint) -> QPoint:
        """Convert widget coordinates to image coordinates"""
        if self.display_rect is None or self.image.isNull():
            return widget_pos

        x = int((widget_pos.x() - self.display_rect.x()) / self.scale_factor)
        y = int((widget_pos.y() - self.display_rect.y()) / self.scale_factor)

        x = max(0, min(x, self.image.width() - 1))
        y = max(0, min(y, self.image.height() - 1))

        return QPoint(x, y)


class CropPreviewWidget(QWidget):
    """Read-only widget that displays an image with crop overlay and emits clicked signal."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image: QImage | None = None
        self.crop_rect: QRect | None = None
        self.setMinimumSize(200, 150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.display_rect: QRect | None = None
        self.image_offset: QPoint | None = None
        self.scale_factor: float = 1.0

    def set_image(self, image: QImage | None):
        self.image = image
        self.update()

    def set_crop_rect(self, rect: QRect | None):
        self.crop_rect = rect
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.image is None or self.image.isNull():
            painter.fillRect(self.rect(), Qt.GlobalColor.lightGray)
            painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Click to crop")
            return

        widget_rect = self.rect()
        image_width = self.image.width()
        image_height = self.image.height()
        widget_width = widget_rect.width()
        widget_height = widget_rect.height()

        scale = min(widget_width / image_width, widget_height / image_height)
        scaled_width = int(image_width * scale)
        scaled_height = int(image_height * scale)

        x_offset = (widget_width - scaled_width) // 2
        y_offset = (widget_height - scaled_height) // 2

        scaled_rect = QRect(x_offset, y_offset, scaled_width, scaled_height)

        painter.drawImage(scaled_rect, self.image)

        self.image_offset = QPoint(x_offset, y_offset)
        self.scale_factor = scale
        self.display_rect = scaled_rect

        if self.crop_rect is None:
            return

        display_crop_rect = QRect(
            self.image_offset.x() + int(self.crop_rect.x() * self.scale_factor),
            self.image_offset.y() + int(self.crop_rect.y() * self.scale_factor),
            int(self.crop_rect.width() * self.scale_factor),
            int(self.crop_rect.height() * self.scale_factor),
        )

        overlay_color = QColor(0, 0, 0, 100)
        painter.setBrush(overlay_color)
        painter.setPen(Qt.PenStyle.NoPen)

        painter.fillRect(
            QRect(0, 0, self.rect().width(), display_crop_rect.top()), overlay_color
        )
        painter.fillRect(
            QRect(
                0,
                display_crop_rect.bottom(),
                self.rect().width(),
                self.rect().height() - display_crop_rect.bottom(),
            ),
            overlay_color,
        )
        painter.fillRect(
            QRect(
                0,
                display_crop_rect.top(),
                display_crop_rect.left(),
                display_crop_rect.height(),
            ),
            overlay_color,
        )
        painter.fillRect(
            QRect(
                display_crop_rect.right(),
                display_crop_rect.top(),
                self.rect().width() - display_crop_rect.right(),
                display_crop_rect.height(),
            ),
            overlay_color,
        )

        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawRect(display_crop_rect)

    def mousePressEvent(self, event):
        self.clicked.emit()
