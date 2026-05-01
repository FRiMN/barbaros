from PySide6.QtWidgets import QVBoxLayout, QListWidget, QListWidgetItem, QLabel
from PySide6.QtCore import Qt
from .base import AbstractFeature


class SettingsFeature(AbstractFeature):
    tab_name = "Settings"
    settings_key_prefix = "settings"

    def __init__(self, parent):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(10, 10, 10, 10)

        self.providers_list = QListWidget()
        self.layout.addWidget(self.providers_list)

        # Заполнить провайдерами из model_manager
        for name, provider_client in self.parent.model_manager.items():
            item = QListWidgetItem(name)
            self.providers_list.addItem(item)

            label = QLabel(str(provider_client.meta.provider_type))
            label.setStyleSheet("color: gray; font-size: 10pt; font-weight: normal;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.providers_list.setItemWidget(item, label)

        self.layout.addStretch()
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def build_layout(self) -> QVBoxLayout:
        return self.layout
