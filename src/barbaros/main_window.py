import re

from ollama import GenerateResponse
from PySide6.QtWidgets import (
    QMainWindow, QTextEdit, QVBoxLayout, QWidget, QPushButton, QComboBox, QHBoxLayout, QLabel, QSizePolicy
)
from PySide6.QtCore import QThread
from PySide6.QtGui import QFont

from .workers import TranslationWorker
from .widgets.filterable_combobox import FilterableComboBox
from .widgets.progress_label import GradientRainbowLabel


TARGET_LANGUAGES = ["ru", "en", "fr", "de", "es", "it", "pt", "ja", "ko", "zh", "ar", "hi", "ua"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setGeometry(100, 100, 400, 400)

        self.layout = self.build_layout()

        main_widget = QWidget()
        main_widget.setLayout(self.layout)

        self.setCentralWidget(main_widget)

    def set_widgets(self):
        from .resources_loader import Resource

        self.orig_text = QTextEdit()
        self.translated_text = QTextEdit(readOnly=True)
        self.translated_text.hide()

        self.translate_button = QPushButton()
        self.translate_button.setText("Translate")
        self.translate_button.clicked.connect(self.handle_translate_button)

        self.target_language_select = QComboBox()
        self.target_language_select.addItems(TARGET_LANGUAGES)
        self.target_language_select.setCurrentIndex(0)

        self.model = FilterableComboBox(self)
        self.model.addItems(Resource.ollama_models.value)
        self.model.on_selection_changed(self.model.items[0])

        self.stats = QLabel("")
        font = QFont()
        font.setPointSize(8)
        self.stats.setFont(font)

        self.progressbar = GradientRainbowLabel("Translating...")
        self.progressbar.hide()

    def build_layout(self) -> QVBoxLayout:
        self.set_widgets()

        select_panel = QHBoxLayout()
        select_panel.addWidget(self.model)
        self.model.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        select_panel.addWidget(QLabel("Target:"))
        select_panel.addWidget(self.target_language_select)

        layout = QVBoxLayout()
        layout.addLayout(select_panel)
        layout.addWidget(self.orig_text)
        layout.addWidget(self.translate_button)
        layout.addWidget(self.progressbar)
        layout.addWidget(self.translated_text)
        layout.addWidget(self.stats)

        return layout

    def translate(self):
        self.translate_button.setDisabled(True)
        self.translate_button.hide()

        text_to_translate = self.orig_text.toPlainText()

        self.translated_text.clear()
        self.progressbar.show()
        self.progressbar.start_animation()
        self.translated_text.hide()
        self.stats.clear()

        # Run translation in a separate thread
        self.translation_thread = QThread(parent=self)
        self.worker = TranslationWorker(
            text_to_translate,
            self.target_language_select.currentText(),
            self.model.selected_item
        )
        self.worker.moveToThread(self.translation_thread)

        self.worker.finished.connect(self.on_translation_finished)
        self.worker.finished.connect(self.translation_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.translation_thread.finished.connect(self.translation_thread.deleteLater)
        self.translation_thread.started.connect(self.worker.run)

        self.translation_thread.start()

    def pop_think(self, text: str) -> tuple[str, str]:
        m = re.search(r'<think>.*?<\/think>', text, re.MULTILINE | re.DOTALL)
        if m:
            think_text = m.group(0)
            text = text[len(think_text):]
            return think_text, text.strip()
        return '', text

    def on_translation_finished(self, resp: GenerateResponse):
        self.progressbar.hide()
        translated_text = resp.response
        _, translated_text = self.pop_think(translated_text)
        self.translated_text.setText(translated_text)
        self.translated_text.show()
        self.translate_button.setDisabled(False)
        self.translate_button.show()

        eval_secs = resp.eval_duration // 1000 / 1000 / 1000
        load_secs = resp.load_duration // 1000 / 1000 / 1000
        eval_speed = resp.eval_count / eval_secs
        self.stats.setText(f"Eval: {eval_secs:.2f}s; Load: {load_secs:.2f}s; {eval_speed:.2f} tokens/s")

    def handle_translate_button(self):
        self.translate()
