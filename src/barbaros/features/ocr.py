"""
TODO:
    - Refactor to states of widgets; before ocr -> ocr -> before translate -> translate
"""

from PySide6.QtWidgets import (
    QVBoxLayout,
    QPushButton,
    QBoxLayout,
    QHBoxLayout,
    QMessageBox,
    QLabel, QSizePolicy,
)
from PySide6.QtCore import QThread
from any_llm.types.completion import ChatCompletion, Choice

from barbaros.features.base import AbstractFeature
from barbaros.widgets.image_manager import ImageManagerWidget
from barbaros.widgets.custom_text_edit import CustomTextEdit
from barbaros.widgets.progress_label import GradientRainbowLabel
from barbaros.widgets.filterable_combobox import ProviderModelComboBox, ModelSelection
from barbaros.workers import OCRWorker, TranslationWorker


class OCRFeature(AbstractFeature):
    settings_key_prefix = "ocr_feature"

    @property
    def tab_name(self) -> str:
        return self.tr("Image")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def build_layout(self) -> QBoxLayout:
        l = QVBoxLayout()

        select_panel = QHBoxLayout()
        select_panel.addWidget(QLabel(self.tr("OCR Model:")))
        select_panel.addWidget(self.ocr_model_select)
        l.addLayout(select_panel)

        l.addWidget(self.image_manager)
        l.addWidget(self.ocr_button)
        l.addWidget(self.ocr_text)
        l.addWidget(self.translate_button)
        l.addWidget(self.translated_text)
        l.addWidget(self.progressbar)
        l.addWidget(self.stop_button)
        l.addStretch()  # Push everything to the top

        return l

    def set_widgets(self):
        from barbaros.main_window import MainWindow

        self.parent: MainWindow

        self.image_manager = ImageManagerWidget(self.parent)
        self.image_manager.imageCropped.connect(self._handle_image_cropped)

        self.ocr_button = QPushButton(self.tr("OCR"))
        self.ocr_button.setToolTip(self.tr("Get text from image"))
        self.ocr_button.clicked.connect(self.handle_ocr_button)
        self.ocr_button.setDisabled(True)

        self.translate_button = QPushButton(self.tr("Translate"))
        self.translate_button.setToolTip(self.tr("Translate text extracted via OCR"))
        self.translate_button.clicked.connect(self.handle_translate_button)
        self.translate_button.setDisabled(True)

        self.progressbar = GradientRainbowLabel(self.tr("Processing..."))
        self.progressbar.hide()

        self.stop_button = QPushButton()
        self.stop_button.setText(self.tr("Stop"))
        self.stop_button.hide()
        self.stop_button.clicked.connect(self.handle_stop_button)

        self.ocr_text = CustomTextEdit(readOnly=True)

        self.translated_text = CustomTextEdit(readOnly=True)

        self.ocr_model_select = ProviderModelComboBox()
        self.ocr_model_select.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.ocr_model_select.setModelManager(self.parent.model_manager)
        self.ocr_model_select.selectionChanged.connect(self.save_choosed_ocr_model)

        self._restore_past_model_selection()

    def _restore_past_model_selection(self):
        if past_selection := self.settings.value("model"):
            if isinstance(past_selection, ModelSelection):
                self.ocr_model_select.on_selection_changed(past_selection)
            else:
                print("Saved OCR model in wrong format: ignore")

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

        self._disable_action_buttons(True)
        self.progressbar.show()
        self.progressbar.start_animation()
        self.stop_button.show()

        self._threaded_ocr()

    def handle_translate_button(self):
        text = self.ocr_text.toPlainText().strip()
        if not text:
            return

        self.translated_text.clear()

        self._disable_action_buttons(True)
        self.progressbar.show()
        self.progressbar.start_animation()
        self.stop_button.show()

        self._threaded_translate(text)

    def _threaded_ocr(self):
        ocr_thread = QThread(parent=self)
        ocr_thread.finished.connect(ocr_thread.deleteLater)

        selected_item = self.parent.model.selected_item
        provider = self.parent.model_manager[selected_item.provider]
        image_bytes = self.image_manager.get_cropped_image_bytes()

        self.ocr_worker = OCRWorker(
            image_bytes,
            self.ocr_model_select.selected_item,
            provider
        )
        self.ocr_worker.moveToThread(ocr_thread)

        self.ocr_worker.finished.connect(self.on_worker_finished)
        self.ocr_worker.done.connect(self.on_ocr_done)

        self.ocr_worker.finished.connect(ocr_thread.quit)
        self.ocr_worker.finished.connect(self.ocr_worker.deleteLater)
        self.ocr_worker.error.connect(self.on_ocr_error)
        ocr_thread.started.connect(self.ocr_worker.run)

        ocr_thread.start()

    def _threaded_translate(self, text_to_translate: str):
        translation_thread = QThread(parent=self)
        translation_thread.finished.connect(translation_thread.deleteLater)

        selected_item = self.parent.model.selected_item
        provider = self.parent.model_manager[selected_item.provider]
        self.translation_worker = TranslationWorker(
            text_to_translate,
            self.parent.target_language_select.currentText(),
            selected_item,
            provider
        )
        self.translation_worker.moveToThread(translation_thread)

        self.translation_worker.finished.connect(self.on_worker_finished)
        self.translation_worker.done.connect(self.on_translation_done)

        self.translation_worker.finished.connect(translation_thread.quit)
        self.translation_worker.finished.connect(self.translation_worker.deleteLater)
        self.translation_worker.error.connect(self.on_translation_error)
        translation_thread.started.connect(self.translation_worker.run)

        translation_thread.start()

    def on_worker_finished(self):
        self.progressbar.hide()
        self._disable_action_buttons(False)
        self.stop_button.hide()

    def on_translation_done(self, resp: ChatCompletion):
        r: Choice = resp.choices[0]
        translated_text = r.message.content
        self.translated_text.setText(translated_text)

    def on_ocr_done(self, resp: ChatCompletion):
        r: Choice = resp.choices[0]
        ocr_text = r.message.content
        self.ocr_text.setText(ocr_text)

    def on_translation_error(self, error_msg: str):
        self._on_worker_error(error_msg, self.tr("Translation Error"))

    def on_ocr_error(self, error_msg: str):
        self._on_worker_error(error_msg, self.tr("OCR Error"))

    def _on_worker_error(self, error_msg: str, title: str):
        self.progressbar.hide()
        QMessageBox.critical(self.parent, title, error_msg)
        self._disable_action_buttons(False)
        self.stop_button.hide()

    def handle_clear_button(self):
        self.ocr_text.clear()
        self.translated_text.clear()
        self.image_manager.clear()

        self._disable_action_buttons(False)

    def handle_stop_button(self):
        if hasattr(self, "translation_worker"):
            self.translation_worker.cancel()
        if hasattr(self, "ocr_worker"):
            self.ocr_worker.cancel()

    def _disable_action_buttons(self, is_disable: bool):
        self.translate_button.setDisabled(is_disable)
        self.ocr_button.setDisabled(is_disable)

