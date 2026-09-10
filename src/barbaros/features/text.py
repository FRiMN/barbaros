import re

from any_llm.types.completion import ChatCompletion, Choice

from PySide6.QtWidgets import (
    QVBoxLayout,
    QPushButton,
    QHBoxLayout,
    QBoxLayout,
    QMessageBox,
)
from PySide6.QtCore import QThread

from barbaros.features.base import AbstractFeature
from barbaros.widgets.custom_text_edit import CustomTextEdit
from barbaros.widgets.progress_label import GradientRainbowLabel
from barbaros.workers import TranslationWorker


class TextFeature(AbstractFeature):
    settings_key_prefix = "text_feature"

    @property
    def tab_name(self) -> str:
        return self.tr("Text")

    def build_layout(self) -> QBoxLayout:
        l = QVBoxLayout()

        select_panel = QHBoxLayout()

        l.addLayout(select_panel)
        l.addWidget(self.orig_text)
        l.addWidget(self.translate_button)
        l.addWidget(self.progressbar)
        l.addWidget(self.stop_button)
        l.addWidget(self.translated_text)

        return l

    def set_widgets(self):
        self.orig_text = CustomTextEdit()
        self.translated_text = CustomTextEdit(readOnly=True)
        self.translated_text.hide()

        self.translate_button = QPushButton()
        self.translate_button.setText(self.tr("Translate"))
        self.translate_button.clicked.connect(self.handle_translate_button)
        self.translate_button.setShortcut("Ctrl+Return")

        self.progressbar = GradientRainbowLabel(self.tr("Translating..."))
        self.progressbar.hide()

        self.stop_button = QPushButton()
        self.stop_button.setText(self.tr("Stop"))
        self.stop_button.hide()
        self.stop_button.clicked.connect(self.handle_stop_button)

    def handle_translate_button(self):
        self.translate()

    def translate(self):
        text_to_translate = self.orig_text.toPlainText().strip()

        self.translated_text.clear()

        if not text_to_translate:
            return

        self.translate_button.setDisabled(True)
        self.translate_button.hide()
        self.progressbar.show()
        self.progressbar.start_animation()
        self.stop_button.show()
        self.translated_text.hide()

        self._threaded_translate(text_to_translate)

    def _threaded_translate(self, text_to_translate: str):
        # Run translation in a separate thread
        from barbaros.main_window import MainWindow

        self.parent: MainWindow
        self._translation_thread = QThread(parent=self)
        self._translation_thread.finished.connect(self._translation_thread.deleteLater)

        selected_item = self.parent.model.selected_item
        provider = self.parent.model_manager[selected_item.provider]
        lang = self.parent.target_language_select.currentText(),
        self.worker = TranslationWorker(
            text_to_translate, lang, selected_item, provider
        )
        self.worker.moveToThread(self._translation_thread)

        self.worker.finished.connect(self.on_translation_finished)
        self.worker.done.connect(self.on_translation_done)

        self.worker.finished.connect(self._translation_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.on_translation_error)
        self._translation_thread.started.connect(self.worker.run)

        self._translation_thread.start()

    def pop_think(self, text: str) -> tuple[str, str]:
        m = re.search(r"<think>.*?<\/think>", text, re.MULTILINE | re.DOTALL)
        if m:
            think_text = m.group(0)
            text = text[len(think_text) :]
            return think_text, text.strip()
        return "", text

    def on_translation_finished(self):
        self.progressbar.hide()
        self.stop_button.hide()

        self.translate_button.setDisabled(False)
        self.translate_button.show()

    def on_translation_done(self, resp: ChatCompletion):
        r: Choice = resp.choices[0]
        translated_text = r.message.content
        # TODO: We have `reasoning` in ChatCompletionMessage. I think we not need this.
        _, translated_text = self.pop_think(translated_text)
        translated_text = translated_text.strip()
        self.translated_text.setText(translated_text)
        self.translated_text.show()

    def on_translation_error(self, error_msg: str):
        self.progressbar.hide()
        self.stop_button.hide()
        QMessageBox.critical(self.parent, self.tr("Translation Error"), error_msg)
        self.translate_button.setDisabled(False)
        self.translate_button.show()

    def handle_clear_button(self):
        self.orig_text.clear()
        self.translated_text.clear()

    def handle_stop_button(self):
        self.worker.cancel()
