from typing import Optional, List

from PySide6.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QLineEdit,
    QListWidget,
    QAbstractItemView,
    QFrame,
)
from PySide6.QtCore import Signal, Qt, QPoint
from PySide6.QtGui import QFontMetrics

from .link_label import LinkLabel


class FilterableComboBox(QWidget):
    selectionChanged = Signal(str)

    selected_item = None

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
        assert item is not None
        if item not in self.items:
            print(f"Warning: Selected item '{item}' not found in items list. Falling back to first item.")
            item = self.items[0]

        self.selected_item = item

        # Обрезаем текст с многоточием
        fm = QFontMetrics(self.display_label.font())
        elided_text = fm.elidedText(
            item, Qt.TextElideMode.ElideLeft, self.display_label.width()
        )
        self.display_label.setText(elided_text)

        self.display_label.setToolTip(item)
        self.hide_popup()
        self.selectionChanged.emit(self.selected_item)

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
        layout.setContentsMargins(0, 0, 0, 0)

        self.frame = QFrame(self)
        self.frame.setFrameShape(QFrame.Shape.WinPanel)
        self.frame.setLineWidth(1)

        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)

        # Создаем поле ввода для фильтра
        self.filter_edit = QLineEdit(self.frame)
        self.filter_edit.setPlaceholderText("Filter items")
        self.filter_edit.textChanged.connect(self.apply_filter)
        frame_layout.addWidget(self.filter_edit)

        # Создаем виджет для отображения списка вариантов
        self.list_widget = QListWidget(self.frame)
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemActivated.connect(self.on_item_selected)
        self.list_widget.setStyleSheet("""
            QListWidget::item {
                padding: 4px;
            }
        """)
        frame_layout.addWidget(self.list_widget)

        self.frame.setLayout(frame_layout)
        layout.addWidget(self.frame)

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
