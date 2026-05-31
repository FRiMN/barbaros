from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QLabel,
    QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QScreen, QPainter, QColor, QFont


class ScreenHintWidget(QWidget):
    """Overlay widget displaying a monitor number in the center of the screen."""

    def __init__(self, number: int, screen: QScreen, parent=None):
        super().__init__(parent)
        self.number = number

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        geom = screen.geometry()
        self.setGeometry(geom)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Semi-transparent dark background
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))

        self.paint_circle(painter)
        self.paint_text(painter)

        painter.end()

    def paint_text(self, painter: QPainter):
        """Number text"""
        font = QFont()
        font.setPixelSize(96)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 220))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self.number))

    def paint_circle(self, painter: QPainter):
        """Circle background for the number"""
        radius = 80
        cx = self.width() // 2
        cy = self.height() // 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)


class MonitorSelectDialog(QDialog):
    """Dialog for selecting a monitor from a list of screens."""

    def __init__(self, screens: list[QScreen], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Monitor")
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(300)

        self.screens = screens
        self.selected_screen: QScreen | None = None

        layout = QVBoxLayout()

        label = QLabel("Select a monitor to capture:")
        layout.addWidget(label)

        self.list_widget = QListWidget()
        for i, screen in enumerate(screens):
            geom = screen.geometry()
            item_text = f"Monitor {i + 1}  —  {geom.width()}\u00d7{geom.height()}  ({screen.name()})"
            self.list_widget.addItem(item_text)
        self.list_widget.setCurrentRow(0)
        layout.addWidget(self.list_widget)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        capture_btn = QPushButton("Capture")
        capture_btn.setDefault(True)
        capture_btn.clicked.connect(self._on_capture)
        button_layout.addWidget(capture_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def _on_capture(self):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.screens):
            self.selected_screen = self.screens[row]
            self.accept()
