from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class LinkLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)

        # Начальный стиль, который выглядит как ссылка
        self.setStyleSheet("QLabel { color: lightblue; text-decoration: underline; }")

        # Событие наведения курсора мыши
        self.setCursor(Qt.CursorShape.PointingHandCursor)
