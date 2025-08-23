from PySide6.QtWidgets import (
    QLabel
)
from PySide6.QtCore import Qt

class LinkLabel(QLabel):
    def __init__(self, text, parent=None):
        super(LinkLabel, self).__init__(text, parent)

        # Начальный стиль, который выглядит как ссылка
        self.setStyleSheet("QLabel { color: lightblue; text-decoration: underline; }")

        # Событие наведения курсора мыши
        self.setCursor(Qt.CursorShape.PointingHandCursor)
