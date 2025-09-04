import warnings
import typing

from PySide6.QtWidgets import QTextEdit, QMenu
from PySide6.QtGui import QAction, QShortcut, QKeySequence
from PySide6.QtCore import Qt

class CustomTextEdit(QTextEdit):
    font_size_step = 1  # Define the step for font size adjustment
    font_size_restrictions = (8, 16)  # Define the minimum and maximum font sizes

    def __init__(self, *args, font_size: int | None = None, **kwargs):
        super().__init__(*args, **kwargs)

        if font_size:
            if not (self.font_size_restrictions[0] <= font_size <= self.font_size_restrictions[1]):
                warnings.warn(f"Font size must be between {self.font_size_restrictions[0]} and {self.font_size_restrictions[1]}")
                font_size = max(self.font_size_restrictions[0], min(font_size, self.font_size_restrictions[1]))
            self.setFontPointSize(font_size)

        self.context_menu = self._build_context_menu()

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        self.default_font_size = self.font().pointSize()

    def _build_context_menu(self) -> QMenu:
        context_menu = QMenu(self)

        # Get default actions (Cut, Copy, Paste, etc.)
        default_actions = self.createStandardContextMenu()

        # Iterate through default actions and add them to our custom menu
        # This ensures standard functionality is preserved
        for action in default_actions.actions():
            context_menu.addAction(action)

        # Add a separator before our custom actions
        context_menu.addSeparator()

        # --- Font Size Actions ---
        st_k = QKeySequence.StandardKey

        enlarge_font_action = self._create_action("&Enlarge Font", self.enlarge_font, st_k.ZoomIn)
        context_menu.addAction(enlarge_font_action)

        decrease_font_action = self._create_action("&Decrease Font", self.decrease_font, st_k.ZoomOut)
        context_menu.addAction(decrease_font_action)

        reset_font_action = self._create_action("Reset Font", self.reset_font)
        context_menu.addAction(reset_font_action)

        return context_menu

    def show_context_menu(self, pos):
        # Show the context menu at the cursor position
        self.context_menu.exec(self.mapToGlobal(pos))

    def _create_action(
        self,
        label: str,
        callback: typing.Callable,
        key_seq: QKeySequence | QKeySequence.StandardKey | None = None
    ) -> QAction:
        action = QAction(label, self)
        action.triggered.connect(callback)

        if key_seq is not None:
            action.setShortcut(key_seq)

            shortcut = QShortcut(key_seq, self)
            shortcut.activated.connect(callback)

        return action

    def enlarge_font(self):
        font = self.font()
        if font.pointSize() < self.font_size_restrictions[1]:
            font.setPointSize(font.pointSize() + self.font_size_step)
            self.setFont(font)

    def decrease_font(self):
        font = self.font()
        if font.pointSize() > self.font_size_restrictions[0]:
            font.setPointSize(font.pointSize() - self.font_size_step)
            self.setFont(font)

    def reset_font(self):
        font = self.font()
        font.setPointSize(self.default_font_size)
        self.setFont(font)
