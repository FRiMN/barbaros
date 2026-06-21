from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QScrollArea, QLabel, QPushButton, QHBoxLayout, QMessageBox
)
from PySide6.QtGui import QIcon

from barbaros.widgets.provider_dialog import ProviderDialog
from barbaros.model_manager import ProviderClient, ModelManager
from barbaros.common import truncate_key

if TYPE_CHECKING:
    from barbaros.main_window import MainWindow


class ProvidersCard(QFrame):
    def __init__(self, model_manager: ModelManager, parent: MainWindow):
        super().__init__()
        self.model_manager = model_manager
        self.parent = parent
        self.setup_ui()
        self.refresh()

    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

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

        self.layout.addWidget(scroll)
        self.layout.addLayout(btn_layout)

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

    def _reload_provider_models(self, provider_name: str):
        self.model_manager.start_fetching_models(provider_name)

    def refresh(self):
        while self.cards_container.count() > 1:
            item = self.cards_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for name, provider_client in self.model_manager.items():
            provider_client: ProviderClient

            card = QFrame()
            card.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
            card.setLineWidth(1)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 10, 15, 10)

            header_layout = self._build_header_layout(name)
            card_layout.addLayout(header_layout)

            info_layout = self._build_info_layout(provider_client)
            card_layout.addLayout(info_layout)

            self.cards_container.insertWidget(self.cards_container.count() - 1, card)

    def _build_header_layout(self, name: str) -> QHBoxLayout:
        # Header layout for name and reload button
        header_layout = QHBoxLayout()

        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        header_layout.addWidget(name_label)

        header_layout.addStretch()

        reload_btn = QPushButton()
        reload_btn.setIcon(QIcon.fromTheme("view-refresh", QIcon.fromTheme("reload")))
        reload_btn.setFixedSize(24, 24)
        reload_btn.setToolTip("Reload models")
        reload_btn.clicked.connect(lambda checked, n=name: self._reload_provider_models(n))
        header_layout.addWidget(reload_btn)

        return header_layout

    def _build_info_layout(self, provider_client: ProviderClient) -> QHBoxLayout:
        info_layout = QHBoxLayout()
        info_layout.setSpacing(10)

        info_layout.addWidget(self._create_bordered_label(str(provider_client.meta.provider_type)))

        base = provider_client.meta.api_base
        if base:
            info_layout.addWidget(self._create_bordered_label(self._truncate_url(base)))

        key = provider_client.meta.api_key_manager.get()
        if key:
            info_layout.addWidget(self._create_bordered_label(truncate_key(key)))

        info_layout.addStretch()
        return info_layout

    def _open_provider_dialog(self):
        dialog = ProviderDialog(self.model_manager, self.parent)
        dialog.exec()
        self.refresh()
        self.parent.save_providers()
