from PySide6.QtWidgets import QLabel
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Property, Qt
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QBrush


class GradientRainbowLabel(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("color: black;")
        self._hue_offset = 0
        self.is_animating = False

        # Setup animation
        self.gradient_animation = QPropertyAnimation(self, b"hue_offset")
        self.gradient_animation.setStartValue(0)
        self.gradient_animation.setEndValue(360)
        self.gradient_animation.setDuration(3000)
        self.gradient_animation.setLoopCount(-1)
        self.gradient_animation.setEasingCurve(QEasingCurve.Type.Linear)

        # Initial styling
        self.update_gradient()

    def setHueOffset(self, value):
        self._hue_offset = value
        self.update_gradient()

    def getHueOffset(self):
        return self._hue_offset

    # Qt property registration
    hue_offset = Property(int, getHueOffset, setHueOffset)

    def update_gradient(self):
        # Create gradient with multiple color stops for vibrant effect
        gradient = QLinearGradient(0, 0, self.width(), 0)

        # Add multiple color stops for smooth rainbow effect
        for i in range(7):
            position = i / 6.0
            hue = (self._hue_offset + int(position * 360)) % 360
            color = QColor.fromHsv(hue, 255, 255)
            gradient.setColorAt(position, color)

        # Apply gradient as background
        brush = QBrush(gradient)
        palette = self.palette()
        palette.setBrush(self.backgroundRole(), brush)
        self.setPalette(palette)

    def paintEvent(self, event):
        # Custom painting to ensure gradient works properly
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Create gradient
        gradient = QLinearGradient(0, 0, self.width(), 0)
        for i in range(7):
            position = i / 6.0
            hue = (self._hue_offset + int(position * 360)) % 360
            color = QColor.fromHsv(hue, 255, 255)
            gradient.setColorAt(position, color)

        # Draw rectangle with gradient
        painter.setBrush(QBrush(gradient))
        painter.setPen(QColor(0, 0, 0, 0))  # Transparent pen
        painter.drawRect(0, 0, self.width(), self.height())

        # Call parent to draw text
        painter.end()
        super().paintEvent(event)

    def start_animation(self):
        if not self.is_animating:
            self.gradient_animation.start()
            self.is_animating = True

    def stop_animation(self):
        if self.is_animating:
            self.gradient_animation.stop()
            self.is_animating = False
