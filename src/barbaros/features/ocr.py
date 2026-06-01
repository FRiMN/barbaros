from PySide6.QtWidgets import (
    QVBoxLayout,
    QPushButton,
    QBoxLayout,
    QHBoxLayout,
    QMessageBox,
    QLabel, QSizePolicy,
)
from PySide6.QtCore import QThread, QBuffer, QIODevice
from any_llm.types.completion import ChatCompletion, Choice

from barbaros.features.base import AbstractFeature
from barbaros.widgets.image_manager import ImageManagerWidget
from barbaros.widgets.custom_text_edit import CustomTextEdit
from barbaros.widgets.progress_label import GradientRainbowLabel
from barbaros.widgets.filterable_combobox import FilterableComboBox, ProviderModelComboBox, ModelSelection
from barbaros.workers import OCRWorker, TranslationWorker


class OCRFeature(AbstractFeature):
    tab_name = "Image"
    settings_key_prefix = "ocr_feature"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def build_layout(self) -> QBoxLayout:
        l = QVBoxLayout()

        select_panel = QHBoxLayout()
        select_panel.addWidget(QLabel("OCR Model:"))
        select_panel.addWidget(self.ocr_model_select)
        l.addLayout(select_panel)

        l.addWidget(self.image_manager)
        l.addWidget(self.ocr_button)
        l.addWidget(self.progressbar)
        l.addWidget(self.ocr_text)
        l.addWidget(self.translate_button)
        l.addWidget(self.translated_text)
        l.addStretch()  # Push everything to the top

        return l

    def set_widgets(self):
        from barbaros.main_window import MainWindow

        self.parent: MainWindow

        self.image_manager = ImageManagerWidget(self.parent)
        self.image_manager.imageCropped.connect(self._handle_image_cropped)

        self.ocr_button = QPushButton("OCR")
        self.ocr_button.setToolTip("Get text from image")
        self.ocr_button.clicked.connect(self.handle_ocr_button)
        self.ocr_button.setDisabled(True)

        self.translate_button = QPushButton("Translate")
        self.translate_button.setToolTip("Translate text extracted via OCR")
        self.translate_button.clicked.connect(self.handle_translate_button)
        self.translate_button.setDisabled(True)

        self.progressbar = GradientRainbowLabel("Processing...")
        self.progressbar.hide()

        self.ocr_text = CustomTextEdit(readOnly=True)

        self.translated_text = CustomTextEdit(readOnly=True)

        self.ocr_model_select = ProviderModelComboBox()
        self.ocr_model_select.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.ocr_model_select.setModelManager(self.parent.model_manager)
        self.ocr_model_select.selectionChanged.connect(self.save_choosed_ocr_model)

        # Restore past model selection
        if past_selection := self.settings.value("model"):
            if isinstance(past_selection, ModelSelection) and self.ocr_model_select.has_item(past_selection):
                self.ocr_model_select.on_selection_changed(past_selection)
            else:
                self.ocr_model_select.on_selection_changed(self.ocr_model_select.get_first_item())

    def save_choosed_ocr_model(self, model: str):
        self.settings.setValue("model", model)

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

        self.ocr_button.setDisabled(True)
        self.translate_button.setDisabled(True)
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
            self.ocr_model_select.selected_item,
        )
        self.worker.moveToThread(ocr_thread)

        self.worker.finished.connect(self.on_ocr_finished)
        self.worker.finished.connect(ocr_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.on_ocr_error)
        ocr_thread.started.connect(self.worker.run)

        ocr_thread.start()

    def on_ocr_finished(self, ocr_text: str):
        self.progressbar.hide()
        self.ocr_text.setText(ocr_text)
        self.translate_button.setDisabled(False)
        self.ocr_button.setDisabled(False)

    def on_ocr_error(self, error_msg: str):
        self.progressbar.hide()
        QMessageBox.critical(self.parent, "OCR Error", error_msg)
        self.ocr_button.setDisabled(False)

    def handle_translate_button(self):
        text = self.ocr_text.toPlainText().strip()
        if not text:
            return

        self.translated_text.clear()

        self.translate_button.setDisabled(True)
        self.progressbar.show()
        self.progressbar.start_animation()

        self._threaded_translate(text)

    def _threaded_translate(self, text_to_translate: str):
        translation_thread = QThread(parent=self)
        translation_thread.finished.connect(translation_thread.deleteLater)

        selected_item = self.parent.model.selected_item
        client = self.parent.model_manager[selected_item.provider].client
        self.translation_worker = TranslationWorker(
            text_to_translate,
            self.parent.target_language_select.currentText(),
            selected_item,
            client
        )
        self.translation_worker.moveToThread(translation_thread)

        self.translation_worker.finished.connect(self.on_translation_finished)
        self.translation_worker.finished.connect(translation_thread.quit)
        self.translation_worker.finished.connect(self.translation_worker.deleteLater)
        self.translation_worker.error.connect(self.on_translation_error)
        translation_thread.started.connect(self.translation_worker.run)

        translation_thread.start()

    def on_translation_finished(self, resp: ChatCompletion):
        self.progressbar.hide()
        r: Choice = resp.choices[0]
        translated_text = r.message.content
        translated_text = translated_text.strip()
        self.translated_text.setText(translated_text)
        self.translate_button.setDisabled(False)

    def on_translation_error(self, error_msg: str):
        self.progressbar.hide()
        QMessageBox.critical(self.parent, "Translation Error", error_msg)
        self.translate_button.setDisabled(False)

    def handle_clear_button(self):
        self.ocr_text.clear()
        self.translated_text.clear()
        self.image_manager.clear()

        self.translate_button.setDisabled(True)
