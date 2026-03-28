import time

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QDialog,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QImage, QScreen

from barbaros.widgets.image_crop import CropPreviewWidget, CropDialog
from barbaros.widgets.screen_capture import MonitorSelectDialog, ScreenHintWidget


class ImageManagerWidget(QWidget):
    """Composite widget for managing images with load, screenshot, and crop functionality"""

    imageCropped = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self._main_window = parent

        self._loaded_image: QImage | None = None
        self._cropped_image: QImage | None = None
        self._crop_rect: QRect | None = None

        self._setup_ui()

    def _setup_ui(self):
        self._create_widgets()

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self._load_button)
        buttons_layout.addWidget(self._screenshot_button)
        layout.addLayout(buttons_layout)

        layout.addWidget(self._crop_preview)

        self.setLayout(layout)

    def _create_widgets(self):
        self._load_button = QPushButton("Load Image")
        self._load_button.setToolTip("Load an image for processing")
        self._load_button.clicked.connect(self._handle_load_image)

        self._screenshot_button = QPushButton("Screenshot")
        self._screenshot_button.setToolTip("Capture a screenshot for processing")
        self._screenshot_button.clicked.connect(self._handle_screenshot)

        self._crop_preview = CropPreviewWidget()
        self._crop_preview.clicked.connect(self._handle_crop_preview_clicked)

    def set_image(self, image: QImage, file_path: str):
        """Set an image programmatically"""
        self._loaded_image = image
        self._cropped_image = None
        self._crop_rect = None
        self._crop_preview.set_image(image)
        self._crop_preview.set_crop_rect(None)
        self.imageCropped.emit()

    def get_loaded_image(self) -> QImage | None:
        """Get the currently loaded (pre-crop) image"""
        return self._loaded_image

    def get_cropped_image(self) -> QImage | None:
        """Get the cropped image"""
        return self._cropped_image

    def get_crop_rect(self) -> QRect | None:
        """Get the crop rectangle"""
        return self._crop_rect

    def clear(self):
        """Clear all image state"""
        self._loaded_image = None
        self._cropped_image = None
        self._crop_rect = None
        self._crop_preview.set_image(None)
        self._crop_preview.set_crop_rect(None)
        self.imageCropped.emit()

    def _handle_load_image(self):
        """Handle load image button click - open file dialog and load selected image"""
        file_dialog = QFileDialog()
        file_dialog.setWindowTitle("Select Image")
        file_dialog.setNameFilter(
            "Images (*.png *.xpm *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)"
        )
        file_dialog.setViewMode(QFileDialog.ViewMode.Detail)

        if not file_dialog.exec():
            return

        selected_files = file_dialog.selectedFiles()
        file_path = selected_files[0]

        image = QImage(file_path)

        if image.isNull():
            self._loaded_image = None
            self._cropped_image = None
            self._crop_rect = None
            self._crop_preview.set_image(None)
            self.imageCropped.emit()
            return

        self.set_image(image, file_path)

    def _get_screen_for_screenshot(self) -> QScreen | None:
        """Get screen for screenshot capture"""
        app = QApplication.instance()
        screens = app.screens()

        if len(screens) == 1:
            return screens[0]

        dialog = MonitorSelectDialog(screens, self._main_window)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        hints = []
        for i, screen in enumerate(screens):
            hint = ScreenHintWidget(i + 1, screen)
            hints.append(hint)
            hint.show()

        res = dialog.exec()

        for hint in hints:
            hint.close()
            hint.deleteLater()

        if res == QDialog.DialogCode.Accepted and dialog.selected_screen is not None:
            return dialog.selected_screen

        return None

    def _take_screenshot(self, screen: QScreen) -> QImage:
        """Capture screenshot from screen"""
        self._main_window.hide()
        QApplication.processEvents()
        time.sleep(0.3)

        geom = screen.geometry()
        image = screen.grabWindow(0, 0, 0, geom.width(), geom.height())

        self._main_window.show()

        return image.toImage()

    def _handle_screenshot(self):
        """Handle screenshot button click"""
        screen = self._get_screen_for_screenshot()

        if screen:
            image = self._take_screenshot(screen)
            self.set_image(image, "screenshot.png")

    def _handle_crop_preview_clicked(self):
        """Handle crop preview click - open crop dialog"""
        if self._loaded_image is None:
            return

        dialog = CropDialog(self._loaded_image, initial_crop_rect=self._crop_rect)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._cropped_image = dialog.get_cropped_image()
        self._crop_rect = dialog.get_crop_rect()
        self._crop_preview.set_crop_rect(self._crop_rect)

        self.imageCropped.emit()
