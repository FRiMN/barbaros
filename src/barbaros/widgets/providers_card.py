from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStyle,
    QVBoxLayout,
)

from barbaros.model_manager import ModelManager, ProviderClient
from barbaros.security import Availability
from barbaros.widgets.provider_dialog import ProviderDialog

if TYPE_CHECKING:
    from barbaros.main_window import MainWindow


class ProvidersCard(QFrame):
    def __init__(self, model_manager: ModelManager, parent: MainWindow):
        super().__init__()
        self.model_manager = model_manager
        self.parent = parent
        self.setup_ui()
        self.refresh()

        # The card renders a snapshot of the manager, but the manager changes
        # behind it: a fetch stores its model list (loaded_list_models) and
        # "Manage Providers" edits the provider list (added/removed).  Without
        # these subscriptions the card keeps the state from its last rebuild,
        # e.g. the "models are not loaded" icon outlives the fetched list
        # (issue #3).
        model_manager.added.connect(self._on_manager_changed)
        model_manager.removed.connect(self._on_manager_changed)
        model_manager.loaded_list_models.connect(self._on_manager_changed)

    def _on_manager_changed(self, *args) -> None:
        """Rebuild the cards after a provider or model-list change."""
        self.refresh()

    def setup_ui(self):
        self.layout = QVBoxLayout(self)

        # BAR-11: a non-blocking banner instead of a crash or a modal at start.
        self.storage_warning = self._build_storage_warning()
        self.layout.addWidget(self.storage_warning)

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
        manage_btn = QPushButton(self.tr("Manage Providers"))
        manage_btn.clicked.connect(self._open_provider_dialog)
        btn_layout.addWidget(manage_btn)

        self.layout.addWidget(scroll)
        self.layout.addLayout(btn_layout)

    def _build_storage_warning(self) -> QFrame:
        """Warning row for an unusable keyring; hidden while storage is ready."""
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel)

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)

        icon = QLabel()
        style = icon.style()
        warn_icon = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        icon_size = style.pixelMetric(QStyle.PixelMetric.PM_ButtonIconSize)
        icon.setPixmap(warn_icon.pixmap(icon_size))
        layout.addWidget(icon)

        self.storage_warning_label = QLabel()
        self.storage_warning_label.setWordWrap(True)
        layout.addWidget(self.storage_warning_label, 1)

        retry_btn = QPushButton(self.tr("Retry"))
        retry_btn.clicked.connect(self._retry_secret_storage)
        layout.addWidget(retry_btn)

        frame.hide()
        return frame

    def _refresh_storage_status(self) -> None:
        """Show the banner when the keyring is unavailable (BAR-11).

        The probe reads no secret and triggers no unlock prompt; the cards below
        stay usable (keyless providers can still fetch models).
        """
        availability = self.model_manager.secret_storage.availability()
        if availability is Availability.READY:
            self.storage_warning.hide()
            return

        self.storage_warning_label.setText(
            self.tr(
                "The system keyring is unavailable, so API keys cannot be read "
                "or saved. Providers that need a key will not work until this is fixed."
            )
        )
        self.storage_warning.show()

    def _retry_secret_storage(self) -> None:
        """Re-run backend detection, e.g. after the keyring service came up."""
        self.model_manager.secret_storage.availability(refresh=True)
        self._refresh_storage_status()

    def _truncate_url(self, url: str) -> str:
        url_len = len(url)
        if url_len >= 15:
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
        self._refresh_storage_status()

        while self.cards_container.count() > 1:
            item = self.cards_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for name, provider_client in self.model_manager.items():
            card = self._build_card(name, provider_client)
            self.cards_container.insertWidget(self.cards_container.count() - 1, card)

    def _build_card(self, name: str, provider_client: ProviderClient) -> QFrame:
        card = QFrame()
        card.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        card.setLineWidth(1)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 10, 15, 10)

        header_layout = self._build_header_layout(name)
        card_layout.addLayout(header_layout)

        info_layout = self._build_info_layout(provider_client)
        card_layout.addLayout(info_layout)

        return card

    def _build_header_layout(self, name: str) -> QHBoxLayout:
        """Header layout for name and reload button"""
        header_layout = QHBoxLayout()

        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        header_layout.addWidget(name_label)

        header_layout.addStretch()

        reload_btn = QPushButton()
        reload_btn.setIcon(QIcon.fromTheme("view-refresh", QIcon.fromTheme("reload")))
        reload_btn.setFixedSize(24, 24)
        reload_btn.setToolTip(self.tr("Reload models"))
        reload_btn.clicked.connect(lambda checked, n=name: self._reload_provider_models(n))
        header_layout.addWidget(reload_btn)

        return header_layout

    def _build_info_layout(self, provider_client: ProviderClient) -> QHBoxLayout:
        """Layout for info and warning icon"""
        info_layout = QHBoxLayout()
        info_layout.setSpacing(10)

        info_layout.addWidget(self._create_bordered_label(str(provider_client.meta.provider_type)))

        base = provider_client.meta.api_base
        if base:
            info_layout.addWidget(self._create_bordered_label(self._truncate_url(base)))

        info_layout.addStretch()

        if not provider_client.models:
            warn_label = self._build_no_models_warn_label()
            info_layout.addWidget(warn_label)

        return info_layout

    def _build_no_models_warn_label(self) -> QLabel:
        warn_label = QLabel()
        warn_label.setToolTip(self.tr("Models are not loaded. Click the button above to refresh the list of models."))

        style = warn_label.style()
        warn_icon = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        icon_size = style.pixelMetric(QStyle.PixelMetric.PM_ButtonIconSize)
        warn_label.setPixmap(warn_icon.pixmap(icon_size))

        return warn_label

    def _open_provider_dialog(self):
        dialog = ProviderDialog(self.model_manager, self.parent)
        dialog.exec()
        self.refresh()
        self.parent.save_providers()
