from PySide6.QtWidgets import QLabel
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Property, Qt
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QBrush, QPaintEvent


class GradientRainbowLabel(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("color: black;")
        self._hue_offset = 0
        self.is_animating = False

        # Setup animation
        self.gradient_animation = anim = QPropertyAnimation(self, b"hue_offset")
        anim.setStartValue(0)
        anim.setEndValue(360)
        anim.setDuration(3000)
        anim.setLoopCount(-1)
        anim.setEasingCurve(QEasingCurve.Type.Linear)

    def setHueOffset(self, value):
        self._hue_offset = value
        # Call paint
        self.update()

    def getHueOffset(self):
        return self._hue_offset

    # Qt property registration
    hue_offset: int = Property(int, getHueOffset, setHueOffset)

    def get_gradient(self) -> QLinearGradient:
        # Create gradient with multiple color stops for vibrant effect
        gradient = QLinearGradient(0, 0, self.width(), 0)

        # Add multiple color stops for smooth rainbow effect
        steps = 100
        for i in range(steps):
            position = i / steps
            hue = (self.hue_offset + int(position * 360)) % 360
            color = QColor.fromHsv(hue, 255, 255)
            gradient.setColorAt(position, color)

        return gradient

    def paintEvent(self, event: QPaintEvent):
        # Custom painting to ensure gradient works properly
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw rectangle with gradient
        brush = QBrush(self.get_gradient())
        painter.setBrush(brush)
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
