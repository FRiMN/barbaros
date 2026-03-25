import re

from ollama import GenerateResponse

from PySide6.QtWidgets import (
    QVBoxLayout,
    QPushButton,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QBoxLayout,
)
from PySide6.QtCore import QThread
from PySide6.QtGui import QFont

from barbaros.features.base import AbstractFeature
from barbaros.widgets.custom_text_edit import CustomTextEdit
from barbaros.widgets.filterable_combobox import FilterableComboBox
from barbaros.widgets.progress_label import GradientRainbowLabel
from barbaros.workers import TranslationWorker


class TextFeature(AbstractFeature):
    tab_name = "Text"

    def build_layout(self) -> QBoxLayout:
        l = QVBoxLayout()

        select_panel = QHBoxLayout()
        select_panel.addWidget(self.model)
        self.model.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        select_panel.addWidget(self.parent.clear_button)
        select_panel.addWidget(QLabel("Target:"))
        select_panel.addWidget(self.parent.target_language_select)

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

        self.model = FilterableComboBox()
        self.model.selectionChanged.connect(self.parent.save_choosed_model)
        self.model.addItems(Resource.ollama_models.value)
        if past_model := self.parent.settings.value("model"):
            self.model.on_selection_changed(past_model)
        else:
            print("set default model")
            self.model.on_selection_changed(self.model.items[0])

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
        print("thread")
        translation_thread = QThread(parent=self)
        translation_thread.finished.connect(translation_thread.deleteLater)

        self.worker = TranslationWorker(
            text_to_translate,
            self.parent.target_language_select.currentText(),
            self.model.selected_item,
        )
        print("before move")
        self.worker.moveToThread(translation_thread)

        self.worker.finished.connect(self.on_translation_finished)
        self.worker.finished.connect(translation_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
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

    def on_translation_finished(self, resp: GenerateResponse):
        self.progressbar.hide()
        translated_text = resp.response
        _, translated_text = self.pop_think(translated_text)
        translated_text = translated_text.strip()
        self.translated_text.setText(translated_text)
        self.translated_text.show()
        self.translate_button.setDisabled(False)
        self.translate_button.show()

        eval_secs = resp.eval_duration // 1000 / 1000 / 1000
        load_secs = resp.load_duration // 1000 / 1000 / 1000
        eval_speed = resp.eval_count / eval_secs
        self.stats.setText(
            f"Eval: {eval_secs:.2f}s; Load: {load_secs:.2f}s; {eval_speed:.2f} tokens/s"
        )

    def handle_clear_button(self):
        self.orig_text.clear()
        self.translated_text.clear()