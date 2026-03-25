from PySide6.QtWidgets import (
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QPushButton,
    QComboBox,
    QTabWidget,
)
from PySide6.QtCore import QRect
from PySide6.QtGui import QCloseEvent, QImage
from PySide6.QtWidgets import QStyle

from .features.ocr import OCRFeature
from .features.text import TextFeature
from .features.base import AbstractFeature
from .common import SettingsProxy, TARGET_LANGUAGES


class MainWindow(QMainWindow):
    settings_key_prefix = "main_window"

    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app
        self.settings = SettingsProxy(self.app.settings, self.settings_key_prefix)
        self.features: list[AbstractFeature] = [
            TextFeature(self),
            OCRFeature(self)
        ]

        if past_geometry := self.settings.value("geometry"):
            self.restoreGeometry(past_geometry)
        else:
            self.setGeometry(100, 100, 400, 400)

        self.layout = self.build_layout()

        main_widget = QWidget()
        main_widget.setLayout(self.layout)

        self.setCentralWidget(main_widget)

    def closeEvent(self, event: QCloseEvent):
        self.settings.setValue("geometry", self.saveGeometry())
        event.accept()

    def save_choosed_model(self, model: str):
        self.settings.setValue("model", model)

    def save_choosed_target_language(self, lang: str):
        self.settings.setValue("target_language", lang)

    def set_widgets(self):
        self.clear_button = QPushButton()
        self.clear_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        self.clear_button.setToolTip("Clear textareas")
        self.clear_button.clicked.connect(self.handle_clear_button)
        clear_button_height = self.clear_button.sizeHint().height()
        self.clear_button.setMaximumWidth(clear_button_height)

        self.target_language_select = tls = QComboBox()
        tls.addItems(TARGET_LANGUAGES)
        tls.currentTextChanged.connect(self.save_choosed_target_language)
        if past_language := self.settings.value("target_language"):
            self.target_language_select.setCurrentIndex(
                TARGET_LANGUAGES.index(past_language)
            )
        else:
            print("set default language")
            self.target_language_select.setCurrentIndex(0)

        for f in self.features:
            f.set_widgets()

    def handle_clear_button(self):
        for f in self.features:
            f.handle_clear_button()

    def build_layout(self) -> QVBoxLayout:
        self.set_widgets()

        tab_widget = QTabWidget()

        for f in self.features:
            tab = QWidget()
            layout = f.build_layout()
            tab.setLayout(layout)
            tab_widget.addTab(tab, f.tab_name)

        main_layout = QVBoxLayout()
        main_layout.addWidget(tab_widget)

        return main_layout
