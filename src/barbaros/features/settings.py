from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QGroupBox
from PySide6.QtCore import Qt
from .base import AbstractFeature

from barbaros.widgets.providers_card import ProvidersCard
from ..widgets.target_language_list_edit import LanguageListEdit

if TYPE_CHECKING:
    from ..main_window import MainWindow


class SettingsFeature(AbstractFeature):
    tab_name = "Settings"
    settings_key_prefix = "settings"

    def __init__(self, parent):
        super().__init__(parent)
        self._first_header_is_set = False
        self.setup_ui()

    def setup_ui(self):
        self.parent: MainWindow

        self.layout = QVBoxLayout()

        self.providers_group = ProvidersGroup(self.parent)
        self.layout.addWidget(self.providers_group)

        self.target_language_group = TargetLanguageListEditGroup(self.parent)
        self.layout.addWidget(self.target_language_group)

        self.layout.addStretch()
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def build_layout(self) -> QVBoxLayout:
        return self.layout


class BaseGroup(QGroupBox):
    name = ""

    def __init__(self, parent: MainWindow):
        super().__init__(self.name)
        self.parent = parent

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.build_ui()

    def build_ui(self):
        pass


class TargetLanguageListEditGroup(BaseGroup):
    name = "Target languages"

    def build_ui(self):
        self.language_list_edit = LanguageListEdit(self.parent)
        self.layout.addWidget(self.language_list_edit)


class ProvidersGroup(BaseGroup):
    name = "Providers"

    def build_ui(self):
        self.providers_card = ProvidersCard(self.parent.model_manager, self.parent)
        self.layout.addWidget(self.providers_card)
