import re
import time

from any_llm.types.completion import ChatCompletion, Choice

from PySide6.QtWidgets import (
    QVBoxLayout,
    QPushButton,
    QHBoxLayout,
    QLabel,
    QBoxLayout,
    QMessageBox,
)
from PySide6.QtCore import QThread
from PySide6.QtGui import QFont

from barbaros.features.base import AbstractFeature
from barbaros.widgets.custom_text_edit import CustomTextEdit
from barbaros.widgets.progress_label import GradientRainbowLabel
from barbaros.workers import TranslationWorker


class TextFeature(AbstractFeature):
    tab_name = "Text"
    settings_key_prefix = "text_feature"

    def build_layout(self) -> QBoxLayout:
        l = QVBoxLayout()

        select_panel = QHBoxLayout()

        l.addLayout(select_panel)
        l.addWidget(self.orig_text)
        l.addWidget(self.translate_button)
        l.addWidget(self.progressbar)
        l.addWidget(self.translated_text)
        l.addWidget(self.stats)

        return l

    def set_widgets(self):
        from ..resources_loader import Resource

        self.orig_text = CustomTextEdit()
        self.translated_text = CustomTextEdit(readOnly=True)
        self.translated_text.hide()

        self.translate_button = QPushButton()
        self.translate_button.setText("Translate")
        self.translate_button.clicked.connect(self.handle_translate_button)
        self.translate_button.setShortcut("Ctrl+Return")

        self.stats = QLabel("")
        font = QFont()
        font.setPointSize(8)
        self.stats.setFont(font)

        self.progressbar = GradientRainbowLabel("Translating...")
        self.progressbar.hide()

    def handle_translate_button(self):
        self.translate()

    def translate(self):
        text_to_translate = self.orig_text.toPlainText().strip()

        self.translated_text.clear()
        self.stats.clear()

        if not text_to_translate:
            return

        self.translate_button.setDisabled(True)
        self.translate_button.hide()
        self.progressbar.show()
        self.progressbar.start_animation()
        self.translated_text.hide()

        self._threaded_translate(text_to_translate)

    def _threaded_translate(self, text_to_translate: str):
        # Run translation in a separate thread
        from barbaros.main_window import MainWindow

        print("thread")
        self.parent: MainWindow
        translation_thread = QThread(parent=self)
        translation_thread.finished.connect(translation_thread.deleteLater)

        selected_item = self.parent.model.selected_item
        client = self.parent.model_manager[selected_item.provider].client
        lang = self.parent.target_language_select.currentText(),
        self.worker = TranslationWorker(
            text_to_translate, lang, selected_item, client
        )
        print("before move")
        self.worker.moveToThread(translation_thread)

        self.worker.finished.connect(self.on_translation_finished)
        self.worker.finished.connect(translation_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self.on_translation_error)
        translation_thread.started.connect(self.worker.run)

        print("before start")
        translation_thread.start()

    def pop_think(self, text: str) -> tuple[str, str]:
        m = re.search(r"<think>.*?<\/think>", text, re.MULTILINE | re.DOTALL)
        if m:
            think_text = m.group(0)
            text = text[len(think_text) :]
            return think_text, text.strip()
        return "", text

    def on_translation_finished(self, resp: ChatCompletion):
        self.progressbar.hide()
        r: Choice = resp.choices[0]
        translated_text = r.message.content
        # TODO: We have `reasoning` in ChatCompletionMessage. I think we not need this.
        _, translated_text = self.pop_think(translated_text)
        translated_text = translated_text.strip()
        self.translated_text.setText(translated_text)
        self.translated_text.show()
        self.translate_button.setDisabled(False)
        self.translate_button.show()

        # eval_secs = resp.eval_duration // 1000 / 1000 / 1000
        # load_secs = resp.load_duration // 1000 / 1000 / 1000
        ended = time.time()
        eval_secs = ended - resp.created
        eval_speed = resp.usage.total_tokens / eval_secs
        self.stats.setText(
            f"Eval: {eval_secs:.2f}s; {eval_speed:.2f} tkn/s"
        )

    def on_translation_error(self, error_msg: str):
        self.progressbar.hide()
        QMessageBox.critical(self.parent, "Translation Error", error_msg)
        self.translate_button.setDisabled(False)
        self.translate_button.show()

    def handle_clear_button(self):
        self.orig_text.clear()
        self.translated_text.clear()
