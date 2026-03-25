import re

from ollama import GenerateResponse

from PySide6.QtWidgets import (
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QPushButton,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTabWidget,
    QFileDialog,
    QDialog,
)
from PySide6.QtCore import QThread, Qt, QRect, QPoint, Slot
from PySide6.QtGui import QFont, QCloseEvent, QImage, QPainter, QPen, QBrush, QColor
from PySide6.QtWidgets import QStyle

from .features.text import TextFeature, AbstractFeature
from .workers import TranslationWorker
from .widgets.filterable_combobox import FilterableComboBox
from .widgets.progress_label import GradientRainbowLabel
from .widgets.custom_text_edit import CustomTextEdit
from .common import SettingsProxy, TARGET_LANGUAGES


class MainWindow(QMainWindow):
    settings_key_prefix = "main_window"

    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app
        self.settings = SettingsProxy(self.app.settings, self.settings_key_prefix)
        self.features: list[AbstractFeature] = [TextFeature(self)]

        self.ocr_loaded_image: QImage | None = None
        self.ocr_cropped_image: QImage | None = None
        self.crop_rect: QRect | None = None

        if past_geometry := self.settings.value("geometry"):
            self.restoreGeometry(past_geometry)
        else:
            self.setGeometry(100, 100, 400, 400)

        self.layout = self.build_layout()

        main_widget = QWidget()
        main_widget.setLayout(self.layout)

        self.setCentralWidget(main_widget)

    def closeEvent(self, event: QCloseEvent):
        self.settings.setValue("geometry", self.saveGeometry())
        event.accept()

    def save_choosed_model(self, model: str):
        self.settings.setValue("model", model)

    def save_choosed_target_language(self, lang: str):
        self.settings.setValue("target_language", lang)

    def set_widgets(self):
        self.clear_button = QPushButton()
        self.clear_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        self.clear_button.setToolTip("Clear textareas")
        self.clear_button.clicked.connect(self.handle_clear_button)
        clear_button_height = self.clear_button.sizeHint().height()
        self.clear_button.setMaximumWidth(clear_button_height)

        self.target_language_select = tls = QComboBox()
        tls.addItems(TARGET_LANGUAGES)
        tls.currentTextChanged.connect(self.save_choosed_target_language)
        if past_language := self.settings.value("target_language"):
            self.target_language_select.setCurrentIndex(
                TARGET_LANGUAGES.index(past_language)
            )
        else:
            print("set default language")
            self.target_language_select.setCurrentIndex(0)

        for f in self.features:
            f.set_widgets()

    def handle_clear_button(self):
        for f in self.features:
            f.handle_clear_button()

    # def _build_text_tab(self) -> QWidget:
    #     translation_tab = QWidget()
    #     translation_layout = self.features[0].build_layout()
    #
    #     translation_tab.setLayout(translation_layout)
    #     return translation_tab

    # def _build_ocr_tab(self) -> QWidget:
    #     ocr_tab = QWidget()
    #     ocr_layout = QVBoxLayout()
    #     ocr_layout.setSpacing(10)
    #
    #     # Button layout for load and crop buttons
    #     button_layout = QHBoxLayout()
    #
    #     self.load_image_button = QPushButton("Load Image")
    #     self.load_image_button.setToolTip("Load an image for OCR processing")
    #     self.load_image_button.clicked.connect(self.handle_load_image_button)
    #     button_layout.addWidget(self.load_image_button)
    #
    #     self.crop_button = QPushButton("Crop")
    #     self.crop_button.setToolTip("Crop the loaded image")
    #     self.crop_button.clicked.connect(self.handle_crop_button)
    #     self.crop_button.setEnabled(False)  # Initially disabled until image is loaded
    #     button_layout.addWidget(self.crop_button)
    #
    #     ocr_layout.addLayout(button_layout)
    #
    #     # Status label to show loaded image info
    #     self.ocr_status_label = QLabel("No image selected")
    #     self.ocr_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    #     self.ocr_status_label.setStyleSheet(
    #         "QLabel { color: #666; font-style: italic; }"
    #     )
    #     ocr_layout.addWidget(self.ocr_status_label)
    #
    #     ocr_layout.addStretch()  # Push everything to the top
    #
    #     ocr_tab.setLayout(ocr_layout)
    #     return ocr_tab

    def build_layout(self) -> QVBoxLayout:
        self.set_widgets()

        tab_widget = QTabWidget()
        # text_tab = self._build_text_tab()
        # ocr_tab = self._build_ocr_tab()

        for f in self.features:
            tab = QWidget()
            layout = f.build_layout()
            tab.setLayout(layout)
            tab_widget.addTab(tab, f.tab_name)

        # tab_widget.addTab(text_tab, "Text")
        # tab_widget.addTab(ocr_tab, "OCR")

        main_layout = QVBoxLayout()
        main_layout.addWidget(tab_widget)

        return main_layout

    # def set_ocr_image(self, image: QImage, file_path: str):
    #     self.ocr_loaded_image = image
    #     filename = file_path.split("/")[-1]  # Get filename from path
    #     self.ocr_status_label.setText(
    #         f"Loaded: {filename} ({image.width()}x{image.height()})"
    #     )
    #     self.ocr_status_label.setStyleSheet(
    #         "QLabel { color: #006600; font-weight: bold; }"
    #     )

    # def handle_load_image_button(self):
    #     """Handle load image button click - open file dialog and load selected image"""
    #     file_dialog = QFileDialog()
    #     file_dialog.setWindowTitle("Select Image for OCR")
    #     file_dialog.setNameFilter(
    #         "Images (*.png *.xpm *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)"
    #     )
    #     file_dialog.setViewMode(QFileDialog.ViewMode.Detail)
    #
    #     if not file_dialog.exec():
    #         return
    #
    #     selected_files = file_dialog.selectedFiles()
    #     file_path = selected_files[0]
    #
    #     # Load the image
    #     image = QImage(file_path)
    #
    #     # Failed to load image
    #     if image.isNull():
    #         self.ocr_loaded_image = None
    #         self.ocr_cropped_image = None
    #         self.crop_rect = None
    #         self.ocr_status_label.setText(f"Failed to load image: {file_path}")
    #         self.ocr_status_label.setStyleSheet("QLabel { color: #cc0000; }")
    #         self.crop_button.setEnabled(False)
    #         return
    #
    #     self.set_ocr_image(image, file_path)
    #     self.crop_button.setEnabled(True)

    # def handle_crop_button(self):
    #     """Handle crop button click - open crop dialog"""
    #     if self.ocr_loaded_image is None:
    #         return
    #
    #     dialog = CropDialog(self.ocr_loaded_image, self)
    #     if dialog.exec() == QDialog.DialogCode.Accepted:
    #         self.ocr_cropped_image = dialog.get_cropped_image()
    #         self.crop_rect = dialog.get_crop_rect()
    #
    #         if self.ocr_cropped_image:
    #             filename = self.ocr_status_label.text().split(" (")[0]
    #             self.ocr_status_label.setText(
    #                 f"{filename} ({self.ocr_cropped_image.width()}x{self.ocr_cropped_image.height()}) [Cropped]"
    #             )
    #             self.ocr_status_label.setStyleSheet(
    #                 "QLabel { color: #006600; font-weight: bold; }"
    #             )


class CropDialog(QDialog):
    """Modal dialog for cropping images with GIMP-like interface"""

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crop Image")
        self.setModal(True)
        self.resize(800, 600)

        self.original_image = image
        self.crop_widget = CropWidget(image)

        layout = QVBoxLayout()
        layout.addWidget(self.crop_widget)
        self.setLayout(layout)

        self.final_crop_rect: QRect | None = None

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
        super().closeEvent(event)


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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.image.isNull():
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

            if self.crop_rect is not None:
                display_crop_rect = QRect(
                    self.image_offset.x() + int(self.crop_rect.x() * self.scale_factor),
                    self.image_offset.y() + int(self.crop_rect.y() * self.scale_factor),
                    int(self.crop_rect.width() * self.scale_factor),
                    int(self.crop_rect.height() * self.scale_factor),
                )

                overlay_color = QColor(0, 0, 0, 100)
                painter.fillRect(self.rect(), overlay_color)
                painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_Clear
                )
                painter.fillRect(display_crop_rect, Qt.GlobalColor.transparent)
                painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_SourceOver
                )

                painter.setPen(QPen(QColor(255, 255, 255), 2))
                painter.drawRect(display_crop_rect)

                self._draw_handles(painter, display_crop_rect)
        else:
            painter.fillRect(self.rect(), Qt.GlobalColor.lightGray)
            painter.setPen(QPen(Qt.GlobalColor.darkGray, 1))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "No image loaded"
            )

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
