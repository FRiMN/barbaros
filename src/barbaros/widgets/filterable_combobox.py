from typing import Optional, List
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QLineEdit,
    QListWidget,
    QAbstractItemView,
    QFrame,
    QTreeWidget,
    QTreeWidgetItem,
)
from PySide6.QtCore import Signal, Qt, QPoint
from PySide6.QtGui import QFontMetrics
from any_llm.types.model import Model

from .link_label import LinkLabel
from ..model_manager import ProviderClient, ModelManager


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

    def clear(self):
        self.items = []
        self.filterable_popup.items = []
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


@dataclass
class ModelSelection:
    """Container for selected provider/model pair."""
    provider: str
    model: str


class ProviderModelTreePopup(QWidget):
    """Tree popup for provider → model selection."""
    selectionChanged = Signal(object)  # emits ModelSelection

    model_manager: ModelManager | None

    def __init__(self, parent=None, model_manager=None):
        super().__init__(parent)
        self.initUI()
        self.setModelManager(model_manager)
        self.provider_items = {}  # provider_name -> QTreeWidgetItem

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.frame = QFrame(self)
        self.frame.setFrameShape(QFrame.Shape.WinPanel)
        self.frame.setLineWidth(1)

        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)

        # Filter input
        self.filter_edit = QLineEdit(self.frame)
        self.filter_edit.setPlaceholderText("Filter models")
        self.filter_edit.textChanged.connect(self.apply_filter)
        frame_layout.addWidget(self.filter_edit)

        # Tree widget for provider/model hierarchy
        self.tree_widget = QTreeWidget(self.frame)
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setAlternatingRowColors(True)
        self.tree_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tree_widget.itemClicked.connect(self.on_item_clicked)
        self.tree_widget.setStyleSheet("""
            QTreeWidget::item {
                padding: 4px;
            }
        """)
        frame_layout.addWidget(self.tree_widget)

        self.frame.setLayout(frame_layout)
        layout.addWidget(self.frame)

    def setModelManager(self, model_manager: ModelManager | None):
        """Set the ModelManager and refresh items."""
        if hasattr(self, "model_manager") and isinstance(self.model_manager, ModelManager):
            self.model_manager.added.disconnect(self.update_items)
            self.model_manager.removed.disconnect(self.update_items)

        self.model_manager = model_manager
        self.update_items()

        if isinstance(model_manager, ModelManager):
            self.model_manager.added.connect(self.update_items)
            self.model_manager.removed.connect(self.update_items)

    def update_items(self):
        """Build tree from model manager."""
        self.tree_widget.clear()
        self.provider_items = {}

        if not self.model_manager:
            return

        for provider_name, provider_client in self.model_manager.items():
            # Create provider as top-level item
            provider_item = QTreeWidgetItem(self.tree_widget)
            provider_item.setText(0, provider_name)
            provider_item.setFlags(provider_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.provider_items[provider_name] = provider_item

            # Add models as children
            for model in provider_client.models:
                model: Model
                model_item = QTreeWidgetItem(provider_item)
                model_item.setText(0, model.id)
                # Store provider reference in child item
                model_item.setData(0, Qt.ItemDataRole.UserRole, provider_name)

        # Expand all providers by default
        for item in self.provider_items.values():
            item.setExpanded(True)

        self.adjustSize()

    def apply_filter(self, text):
        """Filter models by name (providers always visible)."""
        lowered_text = text.lower()

        # First, hide all children
        for provider_name, provider_item in self.provider_items.items():
            child_count = provider_item.childCount()
            for i in range(child_count):
                child = provider_item.child(i)
                model_name = child.text(0).lower()
                should_show = lowered_text in model_name
                child.setHidden(not should_show)

            # Expand provider when filtering to show results
            if lowered_text:
                provider_item.setExpanded(True)

        # If filter is empty, expand all
        if not lowered_text:
            for item in self.provider_items.values():
                item.setExpanded(True)

    def on_item_clicked(self, item, column):
        """Handle item click - only respond to model (child) items."""
        # Check if this is a child item (has parent)
        parent = item.parent()
        if parent is None:
            # It's a provider - toggle expand/collapse
            item.setExpanded(not item.isExpanded())
            return

        # It's a model - emit selection
        provider_name = item.data(0, Qt.ItemDataRole.UserRole)
        model_name = item.text(0)
        selection = ModelSelection(provider=provider_name, model=model_name)
        self.selectionChanged.emit(selection)
        self.hide()

    def show(self, /) -> None:
        super().show()
        self.filter_edit.setFocus()


class ProviderModelComboBox(QWidget):
    """ComboBox for selecting provider/model from ModelManager."""
    selectionChanged = Signal(object)  # emits ModelSelection

    selected_item: Optional[ModelSelection] = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_manager = None
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)

        # Display label
        self.display_label = LinkLabel("", self)
        self.display_label.setMouseTracking(True)
        self.display_label.mousePressEvent = self.show_filterable_popup
        layout.addWidget(self.display_label)
        self._update_label_like_none()

        self.filterable_popup = ProviderModelTreePopup(parent=self)
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

    def setModelManager(self, model_manager):
        """Set the ModelManager and populate the tree."""
        self.model_manager = model_manager
        self.filterable_popup.setModelManager(model_manager)

    def _update_label_like_none(self):
        self.display_label.setText("Select a model")
        self.display_label.setToolTip("")

    def _update_label_like_model(self):
        display_text = self.selected_item.model
        fm = QFontMetrics(self.display_label.font())
        elided_text = fm.elidedText(
            display_text, Qt.TextElideMode.ElideLeft, self.display_label.width()
        )
        self.display_label.setText(elided_text)

        tooltip = f"{self.selected_item.provider}: {self.selected_item.model}"
        self.display_label.setToolTip(tooltip)

    def update_label(self):
        if self.selected_item is None:
            self._update_label_like_none()
            return None

        self._update_label_like_model()

    def on_selection_changed(self, selection: ModelSelection | None):
        """Handle selection."""
        self.selected_item = selection

        self.update_label()
        self.hide_popup()
        self.selectionChanged.emit(self.selected_item)

    def get_first_item(self) -> Optional[ModelSelection]:
        """Return the first available model as ModelSelection."""
        if not self.model_manager:
            print("Model manager not set in ProviderModelComboBox")
            return None

        provider_names = list(self.model_manager.keys())
        if not provider_names:
            print("Providers not found in ProviderModelComboBox")
            return None

        provider_name = provider_names[0]
        provider_client: ProviderClient = self.model_manager[provider_name]

        if not provider_client.models:
            print("Models not found in ProviderModelComboBox")
            return None

        first_model = provider_client.models[0]
        return ModelSelection(provider=provider_name, model=first_model.id)

    def has_item(self, item: ModelSelection) -> bool:
        """Check if the given ModelSelection exists in the model_manager."""
        if not self.model_manager or not item:
            return False

        if item.provider not in self.model_manager:
            return False

        provider_client = self.model_manager[item.provider]

        for model in provider_client.models:
            if model.id == item.model:
                return True

        return False
