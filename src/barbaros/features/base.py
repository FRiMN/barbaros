from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMainWindow, QBoxLayout


class AbstractFeature(QObject):
    tab_name: str
    parent: QMainWindow

    def __init__(self, parent: QMainWindow):
        super().__init__()
        self.parent = parent

    def build_layout(self) -> QBoxLayout:
        raise NotImplementedError("Do implement in concrete class")

    def set_widgets(self):
        pass

    def handle_clear_button(self):
        pass
