from PySide6.QtWidgets import (
    QVBoxLayout,
    QPushButton,
    QBoxLayout,
    QHBoxLayout,
    QSizePolicy,
)
from PySide6.QtCore import QThread, QBuffer, QIODevice

from barbaros.features.base import AbstractFeature
from barbaros.widgets.image_manager import ImageManagerWidget
from barbaros.widgets.custom_text_edit import CustomTextEdit
from barbaros.widgets.progress_label import GradientRainbowLabel
from barbaros.widgets.filterable_combobox import FilterableComboBox
from barbaros.workers import OCRWorker


class OCRFeature(AbstractFeature):
    tab_name = "Image"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def build_layout(self) -> QBoxLayout:
        l = QVBoxLayout()

        select_panel = QHBoxLayout()
        select_panel.addWidget(self.model)
        self.model.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        select_panel.addWidget(self.parent.clear_button)

        l.addLayout(select_panel)

        l.addWidget(self.image_manager)
        l.addWidget(self.ocr_button)
        l.addWidget(self.progressbar)
        l.addWidget(self.ocr_text)
        l.addWidget(self.translated_text)
        l.addStretch()  # Push everything to the top

        return l

    def set_widgets(self):
        from ..resources_loader import Resource

        self.image_manager = ImageManagerWidget(self.parent)
        self.image_manager.imageCropped.connect(self._handle_image_cropped)

        self.ocr_button = QPushButton("OCR")
        self.ocr_button.clicked.connect(self.handle_ocr_button)
        self.ocr_button.setDisabled(True)

        self.progressbar = GradientRainbowLabel("Processing...")
        self.progressbar.hide()

        self.ocr_text = CustomTextEdit(readOnly=True)
        self.ocr_text.hide()

        self.translated_text = CustomTextEdit(readOnly=True)
        self.translated_text.hide()

        self.model = FilterableComboBox()
        self.model.selectionChanged.connect(self.parent.save_choosed_model)
        self.model.addItems(Resource.ollama_models.value)
        if past_model := self.parent.settings.value("model"):
            self.model.on_selection_changed(past_model)
        else:
            print("set default model")
            self.model.on_selection_changed(self.model.items[0])

    def _handle_image_cropped(self):
        """Handle imageCropped signal from ImageManagerWidget"""
        cropped_image = self.image_manager.get_cropped_image()
        if cropped_image is not None:
            self.ocr_button.setDisabled(False)
        else:
            self.ocr_button.setDisabled(True)

    def handle_ocr_button(self):
        cropped_image = self.image_manager.get_cropped_image()
        if cropped_image is None:
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
        cropped_image = self.image_manager.get_cropped_image()

        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        cropped_image.save(buffer, "PNG")
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
