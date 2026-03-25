from PySide6.QtWidgets import (
    QVBoxLayout,
    QPushButton,
    QHBoxLayout,
    QLabel,
    QFileDialog,
    QDialog,
    QBoxLayout,
)
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage

from barbaros.features.base import AbstractFeature
from barbaros.widgets.image_crop import CropWidget


class OCRFeature(AbstractFeature):
    tab_name = "Image"

    def build_layout(self) -> QBoxLayout:
        l = QVBoxLayout()
        # l.setSpacing(10)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.load_image_button)
        button_layout.addWidget(self.crop_button)

        l.addLayout(button_layout)

        l.addWidget(self.ocr_status_label)
        l.addStretch()  # Push everything to the top

        return l

    def set_widgets(self):
        self.load_image_button = QPushButton("Load Image")
        self.load_image_button.setToolTip("Load an image for OCR processing")
        self.load_image_button.clicked.connect(self.handle_load_image_button)

        self.crop_button = QPushButton("Crop")
        self.crop_button.setToolTip("Crop the loaded image")
        self.crop_button.clicked.connect(self.handle_crop_button)
        self.crop_button.setEnabled(False)  # Initially disabled until image is loaded

        self.ocr_status_label = QLabel("No image selected")
        self.ocr_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ocr_status_label.setStyleSheet(
            "QLabel { color: #666; font-style: italic; }"
        )

    def set_ocr_image(self, image: QImage, file_path: str):
        self.ocr_loaded_image = image
        filename = file_path.split("/")[-1]  # Get filename from path
        self.ocr_status_label.setText(
            f"Loaded: {filename} ({image.width()}x{image.height()})"
        )
        self.ocr_status_label.setStyleSheet(
            "QLabel { color: #006600; font-weight: bold; }"
        )

    def handle_load_image_button(self):
        """Handle load image button click - open file dialog and load selected image"""
        file_dialog = QFileDialog()
        file_dialog.setWindowTitle("Select Image for OCR")
        file_dialog.setNameFilter(
            "Images (*.png *.xpm *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)"
        )
        file_dialog.setViewMode(QFileDialog.ViewMode.Detail)

        if not file_dialog.exec():
            return

        selected_files = file_dialog.selectedFiles()
        file_path = selected_files[0]

        # Load the image
        image = QImage(file_path)

        # Failed to load image
        if image.isNull():
            self.ocr_loaded_image = None
            self.ocr_cropped_image = None
            self.crop_rect = None
            self.ocr_status_label.setText(f"Failed to load image: {file_path}")
            self.ocr_status_label.setStyleSheet("QLabel { color: #cc0000; }")
            self.crop_button.setEnabled(False)
            return

        self.set_ocr_image(image, file_path)
        self.crop_button.setEnabled(True)

    def handle_crop_button(self):
        """Handle crop button click - open crop dialog"""
        if self.ocr_loaded_image is None:
            return

        dialog = CropDialog(self.ocr_loaded_image)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            print("accepted")
            self.ocr_cropped_image = dialog.get_cropped_image()
            self.crop_rect = dialog.get_crop_rect()

            if self.ocr_cropped_image:
                filename = self.ocr_status_label.text().split(" (")[0]
                self.ocr_status_label.setText(
                    f"{filename} ({self.ocr_cropped_image.width()}x{self.ocr_cropped_image.height()}) [Cropped]"
                )
                self.ocr_status_label.setStyleSheet(
                    "QLabel { color: #006600; font-weight: bold; }"
                )


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
