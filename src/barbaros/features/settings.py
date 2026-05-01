from PySide6.QtWidgets import QVBoxLayout, QListWidget, QListWidgetItem, QLabel, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt
from .base import AbstractFeature

from barbaros.widgets.provider_dialog import ProviderDialog


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

        self._populate_providers()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        manage_btn = QPushButton("Manage Providers")
        manage_btn.clicked.connect(self._open_provider_dialog)
        btn_layout.addWidget(manage_btn)
        self.layout.addLayout(btn_layout)

        self.layout.addStretch()
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def _populate_providers(self):
        self.providers_list.clear()
        for name, provider_client in self.parent.model_manager.items():
            item = QListWidgetItem(name)
            self.providers_list.addItem(item)
            label = QLabel(str(provider_client.meta.provider_type))
            label.setStyleSheet("color: gray; font-size: 10pt; font-weight: normal;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.providers_list.setItemWidget(item, label)

    def _open_provider_dialog(self):
        dialog = ProviderDialog(self.parent.model_manager, self.parent)
        dialog.exec()
        self._populate_providers()
        self.parent.save_providers()

    def build_layout(self) -> QVBoxLayout:
        return self.layout
