from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QLabel

from barbaros.common import TARGET_LANGUAGES

if TYPE_CHECKING:
    from ..main_window import MainWindow


class LanguageListValidator(QValidator):
    def validate(self, input_str: str, pos: int) -> tuple[QValidator.State, str, int]:
        all_valid = all(
            (1 < len(i.strip()) < 4) and i.strip().isalpha()
            for i in input_str.split(",")
        )
        has_invalid_char = any(
            not c.isalpha() and not c.isspace() and not c == ","
            for c in input_str
        )

        if has_invalid_char:
            return QValidator.State.Invalid, input_str, pos
        elif all_valid:
            return QValidator.State.Acceptable, input_str, pos

        return QValidator.State.Intermediate, input_str, pos

    def fixup(self, input_str: str) -> str:
        return input_str.strip(" ,")


class LanguageListEdit(QWidget):
    """ Widget for editing list of target languages """
    validator = LanguageListValidator()

    def __init__(self, parent: MainWindow, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent = parent
        layout = QVBoxLayout()

        self.language_edit = QLineEdit()
        default_trg_lang_str = ', '.join(TARGET_LANGUAGES)
        self.language_edit.setToolTip(
            f"Comma separated list of target languages in 2 or 3 characters. Default: {default_trg_lang_str}"
        )
        self.language_edit.setText(", ".join(self.parent.target_language_list))
        layout.addWidget(self.language_edit)

        self.language_edit_status = QLabel(
            "Some invalid chars. Valid only comma separated list of target languages in 2 or 3 characters."
        )
        self.language_edit_status.setWordWrap(True)
        self.language_edit_status.setStyleSheet("color: yellow; font-style: oblique;")
        self.language_edit_status.hide()
        layout.addWidget(self.language_edit_status)

        self.language_edit.setValidator(self.validator)
        self.language_edit.editingFinished.connect(self.update_list)
        self.language_edit.textChanged.connect(self._on_lang_list_changed)

        self.setLayout(layout)

    def _on_lang_list_changed(self, text: str):
        status, _, _ = self.validator.validate(text, 0)
        if status == QValidator.State.Intermediate:
            self.language_edit_status.show()
            return
        self.language_edit_status.hide()

    def update_list(self):
        l = [l.strip().lower() for l in self.language_edit.text().split(",")]
        self.parent.target_language_list = l
        self.parent.refresh_target_language_select()
        self.parent.save_target_languages()
