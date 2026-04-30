from PySide6.QtWidgets import QVBoxLayout, QWidget, QLabel, QLineEdit, QPushButton
from PySide6.QtGui import QFont
from .base import AbstractFeature


class SettingsFeature(AbstractFeature):
    tab_name = "Settings"
    settings_key_prefix = "settings"

    def __init__(self, parent):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.layout = QVBoxLayout()
        self.layout.addStretch()

    def build_layout(self) -> QVBoxLayout:
        return self.layout
