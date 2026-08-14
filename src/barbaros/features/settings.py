from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QGroupBox, QComboBox, QLabel
from PySide6.QtCore import Qt
from .base import AbstractFeature

from barbaros.widgets.providers_card import ProvidersCard
from ..widgets.target_language_list_edit import LanguageListEdit
from ..i18n import available_languages, language_display_name

if TYPE_CHECKING:
    from ..main_window import MainWindow


class SettingsFeature(AbstractFeature):
    settings_key_prefix = "settings"

    def __init__(self, parent):
        super().__init__(parent)
        self._first_header_is_set = False
        self.setup_ui()

    @property
    def tab_name(self) -> str:
        return self.tr("Settings")

    def setup_ui(self):
        self.parent: MainWindow

        self.layout = QVBoxLayout()

        self.providers_group = ProvidersGroup(self.parent)
        self.layout.addWidget(self.providers_group)

        self.target_language_group = TargetLanguageListEditGroup(self.parent)
        self.layout.addWidget(self.target_language_group)

        self.language_group = LanguageGroup(self.parent)
        self.layout.addWidget(self.language_group)

        self.layout.addStretch()
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def build_layout(self) -> QVBoxLayout:
        return self.layout


class BaseGroup(QGroupBox):
    def __init__(self, parent: MainWindow):
        super().__init__(parent)
        self.parent = parent
        self.setTitle(self.name)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.build_ui()

    def build_ui(self):
        pass

    @property
    def name(self) -> str:
        return ""


class TargetLanguageListEditGroup(BaseGroup):
    @property
    def name(self) -> str:
        return self.tr("Target languages")

    def build_ui(self):
        self.language_list_edit = LanguageListEdit(self.parent)
        self.layout.addWidget(self.language_list_edit)


class ProvidersGroup(BaseGroup):
    @property
    def name(self) -> str:
        return self.tr("Providers")

    def build_ui(self):
        self.providers_card = ProvidersCard(self.parent.model_manager, self.parent)
        self.layout.addWidget(self.providers_card)


class LanguageGroup(BaseGroup):
    @property
    def name(self) -> str:
        return self.tr("Language")

    def build_ui(self):
        self.lang_combo = QComboBox()
        # Empty data ("") == use system locale
        self.lang_combo.addItem(self.tr("System default"), "")
        # English is the source language, so no .qm file is needed for it.
        self.lang_combo.addItem(self.tr("English"), "en")
        for lang in available_languages():
            self.lang_combo.addItem(self.tr(language_display_name(lang)), lang)

        current = self.parent.app.settings.value("language") or ""
        idx = self.lang_combo.findData(current)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        else:
            print(f"Not found localization from settings: '{current}'")

        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self.layout.addWidget(self.lang_combo)

        hint = QLabel(self.tr("Changes apply after restart."))
        hint.setWordWrap(True)
        self.layout.addWidget(hint)

    def _on_language_changed(self, index: int):
        lang = self.lang_combo.itemData(index)
        self.parent.app.save_language(lang)
