from PySide6.QtWidgets import (
    QMainWindow, QTextEdit, QVBoxLayout, QWidget, QPushButton, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QAbstractItemView
)
from PySide6.QtCore import QThread, Signal
from .workers import TranslationWorker


TARGET_LANGUAGES = ["ru", "en", "fr", "de", "es", "it", "pt", "ja", "ko", "zh", "ar", "hi"]


class FilterableComboBox(QWidget):
    selectionChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)

        # Создаем виджет для отображения текущего выбора
        self.display_label = QLabel("Select an item", self)
        layout.addWidget(self.display_label)

        # Создаем QLineEdit для ввода фильтра
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter items")
        self.filter_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_edit)

        # Создаем QListWidget для отображения списка вариантов
        self.list_widget = QListWidget(self)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemActivated.connect(self.on_item_selected)
        layout.addWidget(self.list_widget)

        # Заполняем список элементами
        items = ["Apple", "Banana", "Cherry", "Date", "Elderberry"]
        for item in items:
            self.list_widget.addItem(item)

    def apply_filter(self, text):
        self.list_widget.clear()
        all_items = ["Apple", "Banana", "Cherry", "Date", "Elderberry"]
        filtered_items = [item for item in all_items if text.lower() in item.lower()]
        for item in filtered_items:
            self.list_widget.addItem(item)

    def on_item_selected(self, item):
        self.display_label.setText(f"Selected: {item.text()}")
        self.selectionChanged.emit(item.text())
        self.filter_edit.clear()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setGeometry(100, 100, 400, 200)

        self.layout = self.build_layout()

        main_widget = QWidget()
        main_widget.setLayout(self.layout)

        self.setCentralWidget(main_widget)

    def set_widgets(self):
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

    def build_layout(self) -> QVBoxLayout:
        self.set_widgets()

        select_panel = QHBoxLayout()
        select_panel.addWidget(QLabel("Target Language:"))
        select_panel.addWidget(self.target_language_select)
        select_panel.addWidget(self.model)

        layout = QVBoxLayout()
        layout.addLayout(select_panel)
        layout.addWidget(self.orig_text)
        layout.addWidget(self.translate_button)
        layout.addWidget(self.translated_text)

        return layout

    def translate(self):
        self.translate_button.setDisabled(True)

        text_to_translate = self.orig_text.toPlainText()

        self.translated_text.clear()
        # self.translated_text.setText("Translating...")

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
        self.translated_text.show()
        self.translate_button.setDisabled(False)

    def handle_translate_button(self):
        self.translate()
