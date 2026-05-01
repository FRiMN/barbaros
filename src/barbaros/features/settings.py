from PySide6.QtWidgets import QVBoxLayout, QScrollArea, QFrame, QLabel, QPushButton, QHBoxLayout, QSizePolicy, QLayout
from PySide6.QtCore import Qt
from .base import AbstractFeature

from barbaros.widgets.providers_card import ProvidersCard



class SettingsFeature(AbstractFeature):
    tab_name = "Settings"
    settings_key_prefix = "settings"

    header_style = "font-size: 4em; font-weight: bold; padding: 10px 0;"

    def __init__(self, parent):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(10, 10, 10, 10)

        header = QLabel("Providers")
        header.setStyleSheet(self.header_style)
        self.providers_card = ProvidersCard(self.parent.model_manager, self.parent)
        self.layout.addWidget(header)
        self.layout.addWidget(self.providers_card)

        self.layout.addStretch()
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def build_layout(self) -> QVBoxLayout:
        return self.layout
