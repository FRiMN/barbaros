from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class LinkLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)

        # Initial style that looks like a link
        self.setStyleSheet("QLabel { color: lightblue; text-decoration: underline; }")

        # Mouse cursor hover event
        self.setCursor(Qt.CursorShape.PointingHandCursor)
