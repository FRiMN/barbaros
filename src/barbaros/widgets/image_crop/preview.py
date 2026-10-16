from PySide6.QtCore import Signal, QRect, Qt, QPoint
from PySide6.QtGui import QImage, QPainter, QPen, QColor
from PySide6.QtWidgets import QWidget


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
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, self.tr("Click to crop")
            )
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
