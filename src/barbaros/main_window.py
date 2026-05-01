from PySide6.QtWidgets import (
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QComboBox,
    QTabWidget, QLabel, QSizePolicy, QLineEdit,
)
from PySide6.QtCore import QRect
from PySide6.QtGui import QCloseEvent, QImage
from PySide6.QtWidgets import QStyle

from .features.ocr import OCRFeature
from .features.text import TextFeature
from .features.settings import SettingsFeature
from .features.base import AbstractFeature
from .common import SettingsProxy, TARGET_LANGUAGES
from .model_manager import ModelManager, default_providers
from .widgets.filterable_combobox import FilterableComboBox



class MainWindow(QMainWindow):
    settings_key_prefix = "main_window"

    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app
        self.settings = SettingsProxy(self.app.settings, self.settings_key_prefix)

        self.model_manager = ModelManager()
        past_providers = self.settings.value("llm_providers", default=default_providers)
        for provider in past_providers:
            self.model_manager.add(provider)

        self.features: list[AbstractFeature] = [
            TextFeature(self),
            OCRFeature(self),
            SettingsFeature(self)
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
        from .resources_loader import Resource

        self.clear_button = QPushButton()
        self.clear_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        self.clear_button.setToolTip("Clear widgets")
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

        self.model = FilterableComboBox()
        self.model.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.model.selectionChanged.connect(self.save_choosed_model)
        self.model.addItems(Resource.ollama_models.value)
        if past_model := self.settings.value("model"):
            self.model.on_selection_changed(past_model)
        else:
            print("set default model")
            self.model.on_selection_changed(self.model.items[0])

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
        
        top_panel = QHBoxLayout()
        top_panel.addWidget(self.model)
        top_panel.addStretch()
        top_panel.addWidget(self.clear_button)
        top_panel.addWidget(QLabel("Target:"))
        top_panel.addWidget(self.target_language_select)

        main_layout.addLayout(top_panel)
        main_layout.addWidget(tab_widget)

        return main_layout

    def handle_clear_button(self):
        for f in self.features:
            f.handle_clear_button()
