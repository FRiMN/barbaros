from PySide6.QtWidgets import QVBoxLayout, QScrollArea, QFrame, QLabel, QPushButton, QHBoxLayout, QSizePolicy, QLayout
from PySide6.QtCore import Qt
from .base import AbstractFeature

from barbaros.widgets.provider_dialog import ProviderDialog
from ..model_manager import ProviderClient


class SettingsFeature(AbstractFeature):
    tab_name = "Settings"
    settings_key_prefix = "settings"

    header_style = "font-size: 4em; font-weight: bold; padding: 10px 0;"

    def __init__(self, parent):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(10, 10, 10, 10)

        self._build_providers_section(self.layout)
        self._populate_providers()

        self.layout.addStretch()
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def _truncate_key(self, key: str) -> str:
        key_len = len(key)
        if 4 <= key_len * 0.15:
            return f"****{key[-4:]}"
        truncate_len = max(1, int(key_len * 0.15))
        return f"****{key[-truncate_len:]}"

    def _truncate_url(self, url: str) -> str:
        url_len = len(url)
        if 15 <= url_len:
            return f"...{url[-15:]}"
        return url

    def _create_bordered_label(self, text: str) -> QFrame:
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.NoFrame)

        label = QLabel(text)
        label.setStyleSheet("color: gray; padding: 2px 2px; border: 1px solid gray;")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 2, 0)
        layout.addWidget(label)
        return frame

    def _build_providers_section(self, layout: QLayout):
        header = QLabel("Providers")
        header.setStyleSheet(self.header_style)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameStyle(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        self.cards_container = QVBoxLayout()
        self.cards_container.setSpacing(10)
        self.cards_container.addStretch()
        container_widget = QFrame()
        container_widget.setLayout(self.cards_container)
        scroll.setWidget(container_widget)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        manage_btn = QPushButton("Manage Providers")
        manage_btn.clicked.connect(self._open_provider_dialog)
        btn_layout.addWidget(manage_btn)

        layout.addWidget(header)
        layout.addWidget(scroll)
        layout.addLayout(btn_layout)

    def _populate_providers(self):
        while self.cards_container.count() > 1:
            item = self.cards_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for name, provider_client in self.parent.model_manager.items():
            provider_client: ProviderClient

            card = QFrame()
            card.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
            card.setLineWidth(1)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 10, 15, 10)

            name_label = QLabel(name)
            name_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
            card_layout.addWidget(name_label)

            info_layout = QHBoxLayout()
            info_layout.setSpacing(10)

            info_layout.addWidget(self._create_bordered_label(str(provider_client.meta.provider_type)))

            base = provider_client.meta.api_base
            if base:
                truncated_base = self._truncate_url(base)
                info_layout.addWidget(self._create_bordered_label(truncated_base))

            key = provider_client.meta.api_key
            if key:
                secure_key = self._truncate_key(key)
                info_layout.addWidget(self._create_bordered_label(secure_key))

            info_layout.addStretch()
            card_layout.addLayout(info_layout)

            self.cards_container.insertWidget(self.cards_container.count() - 1, card)

    def _open_provider_dialog(self):
        dialog = ProviderDialog(self.parent.model_manager, self.parent)
        dialog.exec()
        self._populate_providers()
        self.parent.save_providers()

    def build_layout(self) -> QVBoxLayout:
        return self.layout
