from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QComboBox, QMessageBox, QHeaderView, QFormLayout
)

from any_llm import LLMProvider
from barbaros.common import is_valid_url, truncate_key

from barbaros.model_manager import ModelManager, ProviderMeta


class AddProviderDialog(QDialog):
    def __init__(self, parent=None, provider: ProviderMeta = None):
        super().__init__(parent)
        self.provider = provider
        self.is_edit = provider is not None
        self.setWindowTitle("Edit Provider" if self.is_edit else "Add Provider")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout()

        form = self._build_form()
        layout.addLayout(form)

        btn_layout = self._build_bottom_controls()
        layout.addLayout(btn_layout)

        self.setLayout(layout)

        if self.is_edit:
            self._populate_fields()

    def _populate_fields(self):
        self.name_edit.setText(self.provider.name)
        index = self.type_combo.findData(self.provider.provider_type)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        self.api_key_edit.setText(self.provider.api_key_manager.get() or "")
        self.api_url_edit.setText(self.provider.api_base or "")
        self.name_edit.setEnabled(False)

    def _build_form(self):
        form = QFormLayout()
        self.name_edit = QLineEdit()
        form.addRow("Name:", self.name_edit)

        self.type_combo = QComboBox()
        for p in LLMProvider:
            self.type_combo.addItem(p.value, p)
        form.addRow("Type:", self.type_combo)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key:", self.api_key_edit)

        self.api_url_edit = QLineEdit()
        form.addRow("API URL:", self.api_url_edit)

        return form

    def _build_bottom_controls(self):
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        ok_btn = QPushButton("Save" if self.is_edit else "Add")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._validate)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)

        return btn_layout

    def _validate(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid Input", "Name is required")
            return

        if not self.is_edit and name in self.parent().model_manager.keys():
            QMessageBox.warning(self, "Invalid Input", "Name is exist")
            return

        url = self.api_url_edit.text().strip()
        if url and not is_valid_url(url):
            QMessageBox.warning(self, "Invalid Input", "Invalid API URL format")
            return

        self.accept()

    def get_provider(self) -> ProviderMeta | None:
        if self.result() != QDialog.DialogCode.Accepted:
            return None

        provider = ProviderMeta(
            name=self.name_edit.text().strip(),
            provider_type=self.type_combo.currentData(),
            api_base=self.api_url_edit.text().strip() or None
        )
        api_key = self.api_key_edit.text().strip() or None
        if api_key:
            provider.api_key_manager.set(api_key)

        return provider


class ProviderDialog(QDialog):
    def __init__(self, model_manager: ModelManager, parent=None):
        super().__init__(parent)
        self.model_manager = model_manager
        self.setWindowTitle("Manage Providers")
        self.setModal(True)
        self.resize(700, 400)

        self.table = self._build_table()
        self._populate_table()

        btn_layout = self._build_buttons()

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _build_table(self):
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Name", "Type", "API URL", "API Key"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return table

    def _build_buttons(self):
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_provider)
        btn_layout.addWidget(add_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(self._edit_provider)
        btn_layout.addWidget(edit_btn)

        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._delete_provider)
        btn_layout.addWidget(del_btn)

        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        return btn_layout

    def _populate_table(self):
        self.table.setRowCount(0)
        for name, client in self.model_manager.items():
            row = self.table.rowCount()
            self.table.insertRow(row)

            meta = client.meta
            meta: ProviderMeta
            self.table.setItem(row, 0, QTableWidgetItem(meta.name))
            self.table.setItem(row, 1, QTableWidgetItem(meta.provider_type.value))
            self.table.setItem(row, 2, QTableWidgetItem(meta.api_base or ""))
            key = meta.api_key_manager.get()
            self.table.setItem(row, 3, QTableWidgetItem(truncate_key(key) if key else ""))

    def _add_provider(self):
        dialog = AddProviderDialog(self)
        self._run_provider_dialog(dialog, is_new=True)

    def _edit_provider(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Select a provider to edit")
            return
        name = self.table.item(row, 0).text()
        client = self.model_manager[name]
        provider = client.meta

        dialog = AddProviderDialog(self, provider)
        self._run_provider_dialog(dialog, is_new=False)

    def _run_provider_dialog(self, dialog: AddProviderDialog, is_new: bool):
        if dialog.exec() == QDialog.DialogCode.Accepted:
            provider = dialog.get_provider()
            if provider:
                if is_new and provider.name in self.model_manager:
                    QMessageBox.warning(self, "Duplicate", f"Provider '{provider.name}' already exists")
                    return

                provider.provider_type = LLMProvider.from_string(provider.provider_type)
                if is_new:
                    self.model_manager.add(provider, error_callback=self._show_error)
                else:
                    self.model_manager.update(provider, error_callback=self._show_error)
                self._populate_table()
                self._save()

    def _show_error(self, msg: str):
        QMessageBox.critical(self, "Provider Error", msg)

    def _delete_provider(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Select a provider to delete")
            return
        name = self.table.item(row, 0).text()
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete provider '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.model_manager.remove(name)
            self._populate_table()
            self._save()

    def _save(self):
        from barbaros.main_window import MainWindow

        if parent := self.parent():
            parent: MainWindow
            if hasattr(parent, 'save_providers'):
                parent.save_providers()
