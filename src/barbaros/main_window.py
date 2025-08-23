from typing import Optional, List

from PySide6.QtWidgets import (
    QMainWindow, QTextEdit, QVBoxLayout, QWidget, QPushButton, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QAbstractItemView, QSizePolicy
)
from PySide6.QtCore import QThread, Signal, Qt, QPoint
from PySide6.QtGui import QFontMetrics
from .workers import TranslationWorker


TARGET_LANGUAGES = ["ru", "en", "fr", "de", "es", "it", "pt", "ja", "ko", "zh", "ar", "hi", "ua"]


class LinkLabel(QLabel):
    def __init__(self, text, parent=None):
        super(LinkLabel, self).__init__(text, parent)

        # Начальный стиль, который выглядит как ссылка
        self.setStyleSheet("QLabel { color: lightblue; text-decoration: underline; }")

        # Событие наведения курсора мыши
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class FilterableComboBox(QWidget):
    selectionChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)

        # Создаем виджет для отображения текущего выбора
        self.display_label = LinkLabel("Select an item", self)
        self.display_label.setMouseTracking(True)  # Включаем мониторинг мыши
        self.display_label.mousePressEvent = self.show_filterable_popup
        layout.addWidget(self.display_label)

        self.filterable_popup = FilterablePopup(parent=self)
        self.filterable_popup.selectionChanged.connect(self.on_selection_changed)
        self.filterable_popup.setWindowFlags(Qt.WindowType.Popup)

    def show_filterable_popup(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        pos = self.mapToGlobal(self.display_label.pos())
        popup_pos = pos + QPoint(0, self.display_label.height())
        self.filterable_popup.move(popup_pos)
        self.filterable_popup.show()

    def hide_popup(self):
        if self.filterable_popup.isVisible():
            self.filterable_popup.hide()

    def on_selection_changed(self, item):
        self.selected_item = item

        # Обрезаем текст с многоточием
        fm = QFontMetrics(self.display_label.font())
        elided_text = fm.elidedText(item, Qt.TextElideMode.ElideLeft, self.display_label.width())
        self.display_label.setText(elided_text)

        self.display_label.setToolTip(item)
        self.hide_popup()

    def addItems(self, items: List[str]):
        self.items.extend(items)
        self.filterable_popup.items = self.items
        self.filterable_popup.update_items()


class FilterablePopup(QWidget):
    selectionChanged = Signal(str)

    def __init__(self, parent=None, items: Optional[List[str]] = None):
        super().__init__(parent)
        self.items = items or []
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)

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

        self.update_items()

    def update_items(self):
        self.list_widget.clear()
        font_metrics = QFontMetrics(self.filter_edit.font())
        text_widths = []

        # Заполняем список элементами
        for item in self.items:
            self.list_widget.addItem(item)
            # Расчет ширины строки
            text_width = font_metrics.horizontalAdvance(item)
            text_widths.append(text_width)

        max_width = max(text_widths, default=100)
        self.setFixedWidth(max_width + 20)
        self.adjustSize()

    def apply_filter(self, text):
        lowered_text = text.lower()
        self.list_widget.clear()
        filtered_items = [item for item in self.items if lowered_text in item.lower()]
        for item in filtered_items:
            self.list_widget.addItem(item)

    def on_item_selected(self, item):
        self.selected_item = item.text()
        self.selectionChanged.emit(self.selected_item)
        self.hide()

    def show(self, /) -> None:
        super().show()
        self.filter_edit.setFocus()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setGeometry(100, 100, 400, 200)

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
        layout.addWidget(self.translated_text)

        return layout

    def translate(self):
        self.translate_button.setDisabled(True)

        text_to_translate = self.orig_text.toPlainText()

        self.translated_text.clear()

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

    def on_translation_finished(self, translated_text):
        self.translated_text.setText(translated_text)
        self.translated_text.show()
        self.translate_button.setDisabled(False)

    def handle_translate_button(self):
        self.translate()
