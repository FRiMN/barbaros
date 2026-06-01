from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QBoxLayout

from barbaros.common import SettingsProxy

if TYPE_CHECKING:
    from barbaros.main_window import MainWindow


class AbstractFeature(QObject):
    tab_name: str
    parent: MainWindow
    settings: SettingsProxy
    settings_key_prefix: str

    def __init__(self, parent: MainWindow):
        super().__init__()
        self.parent = parent
        self.settings = SettingsProxy(parent.app.settings, self.settings_key_prefix)

    def build_layout(self) -> QBoxLayout:
        raise NotImplementedError("Do implement in concrete class")

    def set_widgets(self):
        pass

    def handle_clear_button(self):
        pass
