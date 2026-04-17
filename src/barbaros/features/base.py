from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMainWindow, QBoxLayout

from barbaros.common import SettingsProxy


class AbstractFeature(QObject):
    tab_name: str
    parent: QMainWindow
    settings: SettingsProxy
    settings_key_prefix: str

    def __init__(self, parent: QMainWindow):
        super().__init__()
        self.parent = parent
        self.settings = SettingsProxy(parent.app.settings, self.settings_key_prefix)

    def build_layout(self) -> QBoxLayout:
        raise NotImplementedError("Do implement in concrete class")

    def set_widgets(self):
        pass

    def handle_clear_button(self):
        pass
