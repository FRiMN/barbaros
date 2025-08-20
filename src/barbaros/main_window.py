from PySide6.QtWidgets import (
    QMainWindow, QTextEdit, QVBoxLayout, QWidget, QPushButton
)
from PySide6.QtCore import QThread
from .workers import TranslationWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # self.setWindowTitle("Main Window")
        self.setGeometry(100, 100, 400, 300)

        self.layout = self.build_layout()

        main_widget = QWidget()
        main_widget.setLayout(self.layout)

        self.setCentralWidget(main_widget)

    def set_widgets(self):
        self.orig_text = QTextEdit()
        self.translated_text = QTextEdit(readOnly=True)

        self.translate_button = QPushButton()
        self.translate_button.setText("Translate")
        self.translate_button.clicked.connect(self.handle_translate_button)

    def build_layout(self) -> QVBoxLayout:
        self.set_widgets()

        layout = QVBoxLayout()
        layout.addWidget(self.orig_text)
        layout.addWidget(self.translate_button)
        layout.addWidget(self.translated_text)

        return layout

    def translate(self):
        self.translate_button.setDisabled(True)

        text_to_translate = self.orig_text.toPlainText()

        self.translated_text.clear()
        self.translated_text.setText("Translating...")

        # Run translation in a separate thread
        self.translation_thread = QThread(parent=self)
        self.worker = TranslationWorker(text_to_translate)
        self.worker.moveToThread(self.translation_thread)

        self.worker.finished.connect(self.on_translation_finished)
        self.worker.finished.connect(self.translation_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.translation_thread.finished.connect(self.translation_thread.deleteLater)
        self.translation_thread.started.connect(self.worker.run)

        self.translation_thread.start()

    def on_translation_finished(self, translated_text):
        self.translated_text.setText(translated_text)
        self.translate_button.setDisabled(False)

    def handle_translate_button(self):
        self.translate()
