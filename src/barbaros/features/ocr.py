from PySide6.QtWidgets import (
    QVBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QDialog,
    QBoxLayout,
    QHBoxLayout,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QRect, QThread, QBuffer, QIODevice
from PySide6.QtGui import QImage

from barbaros.features.base import AbstractFeature
from barbaros.widgets.image_crop import CropWidget, CropPreviewWidget
from barbaros.widgets.custom_text_edit import CustomTextEdit
from barbaros.widgets.progress_label import GradientRainbowLabel
from barbaros.widgets.filterable_combobox import FilterableComboBox
from barbaros.workers import OCRWorker


class OCRFeature(AbstractFeature):
    tab_name = "Image"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.ocr_loaded_image: QImage | None = None
        self.ocr_cropped_image: QImage | None = None
        self.crop_rect: QRect | None = None

    def build_layout(self) -> QBoxLayout:
        l = QVBoxLayout()

        select_panel = QHBoxLayout()
        select_panel.addWidget(self.model)
        self.model.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        select_panel.addWidget(self.parent.clear_button)

        l.addLayout(select_panel)
        l.addWidget(self.load_image_button)
        l.addWidget(self.crop_preview)
        l.addWidget(self.ocr_button)
        l.addWidget(self.progressbar)
        l.addWidget(self.ocr_text)
        l.addWidget(self.translated_text)
        l.addWidget(self.ocr_status_label)
        l.addStretch()  # Push everything to the top

        return l

    def set_widgets(self):
        from ..resources_loader import Resource

        self.load_image_button = QPushButton("Load Image")
        self.load_image_button.setToolTip("Load an image for OCR processing")
        self.load_image_button.clicked.connect(self.handle_load_image_button)

        self.crop_preview = CropPreviewWidget()
        self.crop_preview.clicked.connect(self.handle_crop_preview_clicked)

        self.ocr_button = QPushButton("OCR")
        self.ocr_button.clicked.connect(self.handle_ocr_button)
        self.ocr_button.setDisabled(True)

        self.progressbar = GradientRainbowLabel("Processing...")
        self.progressbar.hide()

        self.ocr_text = CustomTextEdit(readOnly=True)
        self.ocr_text.hide()

        self.translated_text = CustomTextEdit(readOnly=True)
        self.translated_text.hide()

        self.ocr_status_label = QLabel("No image selected")
        self.ocr_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ocr_status_label.setStyleSheet(
            "QLabel { color: #666; font-style: italic; }"
        )

        self.model = FilterableComboBox()
        self.model.selectionChanged.connect(self.parent.save_choosed_model)
        self.model.addItems(Resource.ollama_models.value)
        if past_model := self.parent.settings.value("model"):
            self.model.on_selection_changed(past_model)
        else:
            print("set default model")
            self.model.on_selection_changed(self.model.items[0])

    def set_ocr_image(self, image: QImage, file_path: str):
        self.ocr_loaded_image = image
        self.crop_preview.set_image(image)
        self.crop_preview.set_crop_rect(None)
        self.ocr_cropped_image = None
        self.crop_rect = None
        self.ocr_button.setDisabled(True)
        filename = file_path.split("/")[-1]
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

        image = QImage(file_path)

        if image.isNull():
            self.ocr_loaded_image = None
            self.ocr_cropped_image = None
            self.crop_rect = None
            self.ocr_button.setDisabled(True)
            self.ocr_status_label.setText(f"Failed to load image: {file_path}")
            self.ocr_status_label.setStyleSheet("QLabel { color: #cc0000; }")
            self.crop_preview.set_image(None)
            return

        self.set_ocr_image(image, file_path)

    def handle_crop_preview_clicked(self):
        """Handle crop button click - open crop dialog"""
        if self.ocr_loaded_image is None:
            return

        dialog = CropDialog(self.ocr_loaded_image, initial_crop_rect=self.crop_rect)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            # TODO: Really need?
            return

        self.ocr_cropped_image = dialog.get_cropped_image()
        self.crop_rect = dialog.get_crop_rect()
        self.crop_preview.set_crop_rect(self.crop_rect)

        if not self.ocr_cropped_image:
            return

        self.ocr_button.setDisabled(False)
        filename = self.ocr_status_label.text().split(" (")[0]
        self.ocr_status_label.setText(
            f"{filename} ({self.ocr_cropped_image.width()}x{self.ocr_cropped_image.height()}) [Cropped]"
        )
        self.ocr_status_label.setStyleSheet(
            "QLabel { color: #006600; font-weight: bold; }"
        )

    def handle_ocr_button(self):
        if self.ocr_cropped_image is None:
            return

        self.ocr_text.clear()
        self.translated_text.clear()
        self.ocr_text.hide()
        self.translated_text.hide()

        self.ocr_button.setDisabled(True)
        self.ocr_button.hide()
        self.progressbar.show()
        self.progressbar.start_animation()

        self._threaded_ocr()

    def _threaded_ocr(self):
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.ocr_cropped_image.save(buffer, "PNG")
        image_bytes = bytes(buffer.data())
        buffer.close()

        ocr_thread = QThread(parent=self)
        ocr_thread.finished.connect(ocr_thread.deleteLater)

        self.worker = OCRWorker(
            image_bytes,
            self.parent.target_language_select.currentText(),
            self.model.selected_item,
        )
        self.worker.moveToThread(ocr_thread)

        self.worker.finished.connect(self.on_ocr_finished)
        self.worker.finished.connect(ocr_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        ocr_thread.started.connect(self.worker.run)

        ocr_thread.start()

    def on_ocr_finished(self, ocr_text: str, translated_text: str):
        self.progressbar.hide()
        self.ocr_text.setText(ocr_text)
        self.ocr_text.show()
        self.translated_text.setText(translated_text)
        self.translated_text.show()
        self.ocr_button.setDisabled(False)
        self.ocr_button.show()

    def handle_clear_button(self):
        self.ocr_text.clear()
        self.translated_text.clear()


class CropDialog(QDialog):
    """Modal dialog for cropping images with GIMP-like interface"""

    def __init__(
        self, image: QImage, parent=None, initial_crop_rect: QRect | None = None
    ):
        super().__init__(parent)
        self.setWindowTitle("Crop Image")
        self.setModal(True)
        self.resize(800, 600)

        self.original_image = image
        self.crop_widget = CropWidget(image)
        initial_crop_rect = initial_crop_rect or QRect(
            0, 0, image.width(), image.height()
        )
        self.crop_widget.set_crop_rect(initial_crop_rect)

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
        self.accept()
