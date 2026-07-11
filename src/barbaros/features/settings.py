from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QLabel, QWidget
from PySide6.QtCore import Qt
from .base import AbstractFeature

from barbaros.widgets.providers_card import ProvidersCard
from ..widgets.target_language_list_edit import LanguageListEdit

if TYPE_CHECKING:
    from ..main_window import MainWindow


class SettingsFeature(AbstractFeature):
    tab_name = "Settings"
    settings_key_prefix = "settings"

    header_style =          "font-size: 4em; font-weight: bold; margin: 1.5em 0 .5em;"
    first_header_style =    "font-size: 4em; font-weight: bold; margin: 0 0 .5em;"
    _first_header_is_set: bool

    def __init__(self, parent):
        super().__init__(parent)
        self._first_header_is_set = False
        self.setup_ui()

    def setup_ui(self):
        self.parent: MainWindow

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(10, 10, 10, 10)

        self.providers_card = ProvidersCard(self.parent.model_manager, self.parent)
        self._build_settings_item("Providers", self.providers_card)

        self.language_edit = LanguageListEdit(parent=self.parent)
        self._build_settings_item("Target languages", self.language_edit)

        self.layout.addStretch()
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def _build_settings_item(self, header_name: str, widget: QWidget):
        header = QLabel(header_name)
        header.setStyleSheet(self.header_style if self._first_header_is_set else self.first_header_style)
        self.layout.addWidget(header)
        self.layout.addWidget(widget)
        self._first_header_is_set = True

    def build_layout(self) -> QVBoxLayout:
        return self.layout
