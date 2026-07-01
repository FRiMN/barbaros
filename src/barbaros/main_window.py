from PySide6.QtWidgets import (
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QComboBox,
    QMessageBox,
    QTabWidget, QLabel, QSizePolicy,
    QStyle
)
from PySide6.QtGui import QCloseEvent
from PySide6.QtCore import Q_ARG, QMetaObject, Qt, Slot

from .features.ocr import OCRFeature
from .features.text import TextFeature
from .features.settings import SettingsFeature
from .features.base import AbstractFeature
from .common import SettingsProxy, TARGET_LANGUAGES, url_to_html_links
from .model_manager import ModelManager, default_providers, ProviderMeta
from .widgets.filterable_combobox import ProviderModelComboBox, ModelSelection



class MainWindow(QMainWindow):
    settings_key_prefix = "main_window"
    settings_llm_providers_key = "llm_providers"
    settings_llm_by_providers_key = "llm_by_providers"

    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app
        self.settings = SettingsProxy(self.app.settings, self.settings_key_prefix)

        self.model_manager = ModelManager()
        self.model_manager.error.connect(self._show_provider_error)
        self.model_manager.loaded_list_models.connect(self.save_models_list)
        past_providers = self.settings.valueFromJson(
            self.settings_llm_providers_key, default=default_providers
        )
        print(f"Loading providers {past_providers}")
        for provider in past_providers:
            p = ProviderMeta.from_dict(provider)
            self.model_manager.add(p)

        self._restore_models_lists()

        # Feature Tabs
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

        self.model_manager.worker_started.connect(self._on_update_fetching_workers)
        self.model_manager.worker_finished.connect(self._on_update_fetching_workers)

        main_widget = QWidget()
        main_widget.setLayout(self.layout)

        self.setCentralWidget(main_widget)

    def _show_provider_error(self, msg: str):
        # Off‑main thread – queue the call
        QMetaObject.invokeMethod(
            self, "_show_provider_error_gui",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, msg)
        )

    @Slot(str)
    def _show_provider_error_gui(self, msg: str):
        msg = url_to_html_links(msg)
        QMessageBox.critical(self, "Provider Error", msg)

    def _restore_models_lists(self):
        from .model_manager import Model

        past_models_lists = self.settings.valueFromJson(self.settings_llm_by_providers_key, default={})
        for provider, models_list in past_models_lists.items():
            if provider not in self.model_manager:
                print(f"Provider `{provider}` not found in Model Manager. Skip model list cache.")
                continue

            models = [Model.model_validate(d) for d in models_list]
            self.model_manager.set_models(provider, models)

    def closeEvent(self, event: QCloseEvent):
        self.settings.setValue("geometry", self.saveGeometry())
        event.accept()

    def save_choosed_model(self, selection: ModelSelection):
        self.settings.setValue("model", selection)

    def save_choosed_target_language(self, lang: str):
        self.settings.setValue("target_language", lang)

    def save_providers(self):
        providers = self.model_manager.to_list()
        print(f"Saving providers {providers}")
        if providers:
            self.settings.setValueAsJson(self.settings_llm_providers_key, providers)
        else:
            # Case: Raise `TypeError: 'NoneType' object is not iterable`
            # while load providers after `past_providers = self.settings.value`.
            # Empty list set like `@Invalid()` in settings.
            self.settings.remove(self.settings_llm_providers_key)

    def save_models_list(self):
        models = self.model_manager.to_models_dict()
        self.settings.setValueAsJson(self.settings_llm_by_providers_key, models)

    def set_widgets(self):
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
        self.restore_target_language()

        self.model = ProviderModelComboBox()
        self.model.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.model.setModelManager(self.model_manager)
        self.model.selectionChanged.connect(self.save_choosed_model)
        self.restore_model()

        self.fetching_workers_label = QLabel()
        self.fetching_workers_label.hide()

        for f in self.features:
            f.set_widgets()
        
    def update_fetching_workers(self, workers: list[str]):
        """Update the fetching workers label with the current count of workers in self.model_manager"""
        count = len(workers)
        l = self.fetching_workers_label
        if count:
            l.setText(f"Active {count} fetching models")
            l.setToolTip(f"Fetching models for providers: {', '.join(workers)}")
            l.show()
        else:
            l.setText("")
            l.setToolTip("")
            l.hide()

    def _on_update_fetching_workers(self, *args, **kwargs):
        self.update_fetching_workers(self.model_manager.fetching_models_active_workers)

    def restore_target_language(self):
        """Restore target language from settings"""
        tls = self.target_language_select

        if past_language := self.settings.value("target_language"):
            tls.setCurrentIndex(TARGET_LANGUAGES.index(past_language))
        else:
            print("set default language")
            tls.setCurrentIndex(0)

    def restore_model(self):
        """Restore model from settings"""
        if past_selection := self.settings.value("model"):
            if isinstance(past_selection, ModelSelection):
                self.model.on_selection_changed(past_selection)
            else:
                print("Saved model in wrong format: ignore")

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
        main_layout.addWidget(self.fetching_workers_label)

        return main_layout
