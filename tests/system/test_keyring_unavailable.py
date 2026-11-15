"""System tests for an unusable keyring (BAR-11, issue #9).

Failed Secret-Dervice/keyring I/O is a normal state: the application must start
and stay usable, an explicit providers action must show a typed status, and a
secret must never be sent, cached, logged or written to disk.  Every test drives
the real composition root (``MainWindow``, ``ProviderDialog``,
``AddProviderDialog``, ``TextFeature``, ``OCRFeature``, ``ModelManager``); only
the external boundaries are substituted: the keyring backend (conftest's
``fake_keyring``/``no_keyring`` fixtures), ``QMessageBox`` and
``AnyLLM.create``.

The store cannot tell whether a key exists when the backend is locked,
unavailable or corrupt, so two behaviours are covered side by side: a local
provider that does not need a key (``ollama``) stays usable - model fetch,
translation and OCR keep working, exactly as the banner promises - while a cloud
provider (``openai``) aborts with the typed ``SecretStorageError`` before
anything is sent.  A cloud provider is never probed without a key: its keyless
constructor is slow and side-effectful (AWS/Google auth chains), so the degraded
path fails fast and must not call ``AnyLLM.create`` at all.

The startup premise changed on purpose in BAR-11: ``ProvidersCard`` no longer
reads a key while the window is built.  The reads happen only on the explicit
"Manage providers" action, which the tests below exercise instead.
"""

from __future__ import annotations

import contextlib
import logging
import os
import uuid
from pathlib import Path

import keyring
from any_llm import LLMProvider
from any_llm.types.completion import ChatCompletion, ChatCompletionMessage, Choice
from any_llm.types.model import Model
from PySide6.QtCore import QThread
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QLabel, QPushButton

import barbaros.features.ocr as ocr_feature_module
import barbaros.features.text as text_feature_module
import barbaros.model_manager as model_manager_module
import barbaros.security as security_module
import barbaros.widgets.provider_dialog as provider_dialog_module
from barbaros.common import truncate_key
from barbaros.main_window import MainWindow
from barbaros.model_manager import ModelManager, ProviderMeta
from barbaros.security import SERVICE_NAME
from barbaros.widgets.filterable_combobox import ModelSelection
from barbaros.widgets.provider_dialog import AddProviderDialog, ProviderDialog

# --- helpers ---------------------------------------------------------------


@contextlib.contextmanager
def open_window(app):
    """Build ``MainWindow`` and always shut its workers down afterwards."""
    window = MainWindow(app=app)
    try:
        yield window
    finally:
        window.model_manager.shutdown()
        window.deleteLater()


def providers_card(window: MainWindow):
    """The ``ProvidersCard`` mounted in the Settings tab."""
    for feature in window.features:
        group = getattr(feature, "providers_group", None)
        if group is not None:
            return group.providers_card
    raise AssertionError("ProvidersCard is not part of the MainWindow")


class RecordingMessageBox:
    """Non-blocking stand-in for ``QMessageBox`` that records modal calls."""

    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    def critical(self, parent, title, text, *args, **kwargs):
        self.calls.append(("critical", title, text))
        return 0

    def question(self, parent, title, text, *args, **kwargs):
        self.calls.append(("question", title, text))
        return 0

    def warning(self, parent, title, text, *args, **kwargs):
        self.calls.append(("warning", title, text))
        return 0


def record_backend_reads(monkeypatch) -> list[tuple[str, str]]:
    """Record reads on the selected keyring backend, without the values.

    BAR-11's store calls ``backend.get_password`` on the vetted backend rather
    than the ``keyring`` module helper, so the spy lives on that instance.
    """
    backend = keyring.get_keyring()
    calls: list[tuple[str, str]] = []
    original = backend.get_password

    def recording(service, username):
        calls.append((service, username))
        return original(service, username)

    monkeypatch.setattr(backend, "get_password", recording)
    return calls


def fill_and_accept_add_dialog(
    dialog: AddProviderDialog, *, name: str, api_key: str
) -> tuple[ProviderMeta | None, str | None]:
    """Fill the real add dialog and press its Add handler."""
    dialog.name_edit.setText(name)
    index = dialog.type_combo.findData(LLMProvider.OPENAI)
    assert index >= 0
    dialog.type_combo.setCurrentIndex(index)
    dialog.api_key_edit.setText(api_key)
    dialog._validate()
    assert dialog.result() == QDialog.DialogCode.Accepted
    return dialog.get_provider(), dialog.get_api_key()


def apply_new_provider(
    provider_dialog: ProviderDialog, *, name: str, api_key: str
) -> bool:
    """Drive the real add-provider transaction exactly as the dialog does."""
    dialog = AddProviderDialog(provider_dialog)
    try:
        provider, key = fill_and_accept_add_dialog(
            dialog, name=name, api_key=api_key
        )
    finally:
        dialog.deleteLater()
    return provider_dialog._apply_provider(provider, key, is_new=True)


def table_provider_names(dialog: ProviderDialog) -> list[str]:
    return [dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())]


def table_row_for(dialog: ProviderDialog, name: str) -> int:
    for row in range(dialog.table.rowCount()):
        if dialog.table.item(row, 0).text() == name:
            return row
    raise AssertionError(f"provider {name!r} is not in the providers table")


def table_text(dialog: ProviderDialog) -> str:
    cells: list[str] = []
    for row in range(dialog.table.rowCount()):
        for column in range(dialog.table.columnCount()):
            item = dialog.table.item(row, column)
            if item is not None:
                cells.append(item.text())
    return "\n".join(cells)


def find_retry_button(card) -> QPushButton:
    for button in card.findChildren(QPushButton):
        if button.text() == "Retry":
            return button
    raise AssertionError("ProvidersCard has no Retry button")


def xdg_directories() -> list[Path]:
    """The redirected XDG directories of the test session."""
    return [
        Path(os.environ[name])
        for name in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME")
        if os.environ.get(name)
    ]


def files_containing(secret: str, roots: list[Path]) -> list[str]:
    """Paths under ``roots`` whose bytes contain ``secret``."""
    needle = secret.encode()
    hits: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                data = path.read_bytes()
            except OSError:  # pragma: no cover - files vanishing mid-scan
                continue
            if needle in data:
                hits.append(str(path))
    return hits


# --- startup: no keyring reads, non-blocking banner -------------------------


def test_main_window_starts_without_reading_the_keyring(
    no_keyring, fake_app, data_home, monkeypatch, caplog
):
    """The window is built from local state only; the banner replaces the crash."""
    key_reads = record_backend_reads(monkeypatch)
    redetections: list[bool] = []
    monkeypatch.setattr(
        security_module,
        "_reset_backend_detection",
        lambda: redetections.append(True),
    )

    with caplog.at_level(logging.WARNING, logger="barbaros.security"):
        window = MainWindow(app=fake_app)
    try:
        # BAR-11: no constructor read at all (it used to crash on fail.Keyring).
        assert key_reads == []

        card = providers_card(window)
        assert not card.storage_warning.isHidden()
        assert card.storage_warning_label.text()

        # The default provider card is still there and the app stays usable.
        assert "ollama" in window.model_manager
        labels = [
            label.text()
            for label in card.cards_container.parentWidget().findChildren(QLabel)
        ]
        assert "ollama" in labels
        assert len(window.features) == 3
        assert window.features[0].translate_button.isEnabled()

        # Retry re-probes storage without a secret read or a restart, and must
        # not raise (it only re-runs backend detection).
        find_retry_button(card).click()
        assert redetections == [True]
        assert not card.storage_warning.isHidden()
    finally:
        window.model_manager.shutdown()
        window.deleteLater()

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.name == "barbaros.security" and record.levelno == logging.WARNING
    ]
    assert any("backend refused" in message for message in warnings)


# --- explicit providers action: typed status instead of a crash -------------


def test_provider_dialog_shows_a_typed_key_status(
    no_keyring, fake_app, data_home, monkeypatch
):
    """The explicit dialog reports "unavailable" and keeps the key cell readable."""
    key_reads = record_backend_reads(monkeypatch)

    with open_window(fake_app) as window:
        # Startup already passed without a read: the premise moved to the dialog.
        assert key_reads == []

        dialog = ProviderDialog(window.model_manager, parent=window)
        try:
            assert dialog.table.rowCount() == 1
            assert dialog.table.item(0, 3).text() == "unavailable"
            assert dialog.table.item(0, 3).toolTip()
            assert not dialog.storage_warning.isHidden()
            assert dialog.storage_warning.text()
            # The refused backend is vetted before any read: the explicit action
            # shows the typed status without touching the keyring at all.
            assert key_reads == []
        finally:
            dialog.deleteLater()


# --- add-provider transaction is aborted on a storage failure ---------------


def test_add_provider_transaction_aborts_when_the_key_cannot_be_saved(
    no_keyring, fake_app, data_home, monkeypatch
):
    """No provider may be added when its key could not be persisted."""
    messages = RecordingMessageBox()
    monkeypatch.setattr(provider_dialog_module, "QMessageBox", messages)

    with open_window(fake_app) as window:
        dialog = ProviderDialog(window.model_manager, parent=window)
        try:
            providers_before = list(window.model_manager)
            table_before = table_provider_names(dialog)
            secret = "sk-BAR11-ABORTED-TRANSACTION"

            assert apply_new_provider(dialog, name="acme", api_key=secret) is False

            assert list(window.model_manager) == providers_before
            assert "acme" not in window.model_manager
            assert table_provider_names(dialog) == table_before

            assert len(messages.calls) == 1
            kind, title, text = messages.calls[0]
            assert (kind, title) == ("critical", "API Key Storage")
            assert text
            assert secret not in str(messages.calls)

            # The transaction is all-or-nothing: the provider is not persisted.
            assert window.settings.value("llm_providers") is None
        finally:
            dialog.deleteLater()


def test_edit_provider_transaction_aborts_when_the_key_cannot_be_saved(
    no_keyring, fake_app, data_home, monkeypatch
):
    """An edit that saves a new key is all-or-nothing too: provider stays unchanged."""
    messages = RecordingMessageBox()
    monkeypatch.setattr(provider_dialog_module, "QMessageBox", messages)
    secret = "sk-BAR11-ABORTED-EDIT"

    with open_window(fake_app) as window:
        window.model_manager.add(
            ProviderMeta("acme", LLMProvider.OPENAI, "https://old.example.com/v1")
        )
        window.save_providers()
        settings_before = window.settings.value("llm_providers")
        assert settings_before

        dialog = ProviderDialog(window.model_manager, parent=window)
        try:
            edit = AddProviderDialog(
                dialog, provider=window.model_manager["acme"].meta
            )
            try:
                # The user edits the endpoint and supplies a new key.
                edit.api_url_edit.setText("https://new.example.com/v1")
                edit.api_key_edit.setText(secret)
                edit._validate()
                assert edit.result() == QDialog.DialogCode.Accepted
                updated = edit.get_provider()
                key = edit.get_api_key()
            finally:
                edit.deleteLater()

            assert updated is not None
            assert updated.api_base == "https://new.example.com/v1"
            assert dialog._apply_provider(updated, key, is_new=False) is False

            # No update happened: name, type and endpoint are the old ones.
            provider = window.model_manager["acme"]
            assert provider.meta.name == "acme"
            assert provider.meta.provider_type is LLMProvider.OPENAI
            assert provider.meta.api_base == "https://old.example.com/v1"

            # No settings write, exactly one critical, no secret in the message.
            assert window.settings.value("llm_providers") == settings_before
            assert len(messages.calls) == 1
            kind, title, text = messages.calls[0]
            assert (kind, title) == ("critical", "API Key Storage")
            assert text
            assert secret not in str(messages.calls)
        finally:
            dialog.deleteLater()


def test_add_provider_transaction_persists_key_and_masks_it(
    fake_keyring, fake_app, data_home, monkeypatch
):
    """With a working store the edit dialog prefills and the table only shows a mask."""
    messages = RecordingMessageBox()
    monkeypatch.setattr(provider_dialog_module, "QMessageBox", messages)
    key_reads = record_backend_reads(monkeypatch)

    with open_window(fake_app) as window:
        # BAR-11: the window was built without any keyring read; the reads below
        # belong to the explicit providers action only.
        assert key_reads == []

        dialog = ProviderDialog(window.model_manager, parent=window)
        try:
            assert key_reads == [(SERVICE_NAME, "ollama")]
            secret = "sk-BAR11-PERSISTED-CORRECT-HORSE"

            assert apply_new_provider(dialog, name="acme", api_key=secret) is True
            assert messages.calls == []
            assert "acme" in window.model_manager
            assert fake_keyring.passwords[(SERVICE_NAME, "acme")] == secret
            assert (SERVICE_NAME, "acme") in key_reads

            # Editing reads the key only through this explicit action.
            edit = AddProviderDialog(dialog, provider=window.model_manager["acme"].meta)
            try:
                assert edit.api_key_edit.text() == secret
                assert edit.key_warning.isHidden()
            finally:
                edit.deleteLater()

            # The providers table masks the key; the full secret never renders.
            dialog._populate_table()
            row = table_row_for(dialog, "acme")
            displayed = dialog.table.item(row, 3).text()
            assert displayed == truncate_key(secret)
            assert displayed.startswith("****")
            assert secret not in displayed
            assert secret not in table_text(dialog)
            assert dialog.storage_warning.isHidden()

            # Provider config is persisted, the key is not.
            persisted = window.settings.value("llm_providers")
            assert "acme" in persisted
            assert secret not in persisted
        finally:
            dialog.deleteLater()


def test_edit_provider_prefill_failure_is_warned_not_silent(no_keyring):
    """A read failure yields an empty field plus an inline warning and tooltip."""
    provider = ProviderMeta("acme", LLMProvider.OPENAI)

    dialog = AddProviderDialog(provider=provider)
    try:
        assert dialog.is_edit
        assert dialog.name_edit.text() == "acme"
        assert dialog.api_key_edit.text() == ""
        assert not dialog.key_warning.isHidden()
        assert dialog.key_warning.text()
        assert dialog.key_warning.toolTip()
    finally:
        dialog.deleteLater()


# --- client creation: keyless providers keep working ------------------------


class FakeKeylessClient:
    """Instant local any-llm client stand-in: no network, no key required."""

    SUPPORTS_COMPLETION_IMAGE = True

    def __init__(self):
        self.list_models_calls = 0
        self.completion_calls = 0

    async def alist_models(self):
        self.list_models_calls += 1
        return []

    async def acompletion(self, model, messages):
        self.completion_calls += 1
        return ChatCompletion(
            id="chatcmpl-keyless-test",
            created=0,
            model=model,
            object="chat.completion",
            choices=[
                Choice(
                    index=0,
                    message=ChatCompletionMessage(role="assistant", content="ok"),
                    finish_reason="stop",
                )
            ],
        )


def keyless_client_factory(monkeypatch):
    """Patch ``AnyLLM.create`` to a recorder returning a fake keyless client."""
    client = FakeKeylessClient()
    calls: list[tuple] = []

    def create(provider_type, api_key=None, api_base=None, **kwargs):
        calls.append((provider_type, api_key, api_base))
        return client

    monkeypatch.setattr(model_manager_module.AnyLLM, "create", create)
    return calls, client


def record_client_creation(monkeypatch) -> list[tuple]:
    """Record ``AnyLLM.create`` calls; a cloud provider must never be probed keyless."""
    client = FakeKeylessClient()
    calls: list[tuple] = []

    def create(provider_type, api_key=None, api_base=None, **kwargs):
        calls.append((provider_type, api_key, api_base))
        return client

    monkeypatch.setattr(model_manager_module.AnyLLM, "create", create)
    return calls


def thread_stopped(thread: QThread) -> bool:
    """Whether a QThread finished (it may already be deleteLater'd)."""
    try:
        return not thread.isRunning()
    except RuntimeError:  # the C++ object was deleted after finishing
        return True


# --- key-requiring provider: abort before anything is sent -------------------


def test_translation_aborts_before_sending_and_restores_the_tab(
    no_keyring, fake_app, data_home, monkeypatch
):
    messages = RecordingMessageBox()
    monkeypatch.setattr(text_feature_module, "QMessageBox", messages)
    client_creations = record_client_creation(monkeypatch)

    with open_window(fake_app) as window:
        window.model_manager.add(ProviderMeta("cloud", LLMProvider.OPENAI))
        feature = window.features[0]
        window.model.on_selection_changed(
            ModelSelection(provider="cloud", model="gpt-4o")
        )
        feature.orig_text.setPlainText("text that must not be sent")

        feature.translate()

        assert len(messages.calls) == 1
        kind, title, text = messages.calls[0]
        assert (kind, title) == ("critical", "Translation Error")
        assert "keyring" in text.lower()
        assert "API key storage is unavailable" in text

        # The tab is restored: the button comes back and no worker is alive.
        assert feature.translate_button.isEnabled()
        assert not feature.translate_button.isHidden()
        assert feature.progressbar.isHidden()
        assert feature.stop_button.isHidden()
        assert feature.findChildren(QThread) == []
        assert not hasattr(feature, "worker")
        assert not hasattr(feature, "_translation_thread")
        # Fail fast: a cloud provider is never probed without a key.
        assert client_creations == []


def test_ocr_aborts_before_sending_and_restores_the_tab(
    no_keyring, fake_app, data_home, monkeypatch
):
    messages = RecordingMessageBox()
    monkeypatch.setattr(ocr_feature_module, "QMessageBox", messages)
    client_creations = record_client_creation(monkeypatch)

    with open_window(fake_app) as window:
        window.model_manager.add(ProviderMeta("cloud", LLMProvider.OPENAI))
        feature = window.features[1]
        selection = ModelSelection(provider="cloud", model="vision-model")
        window.model.on_selection_changed(selection)
        feature.ocr_model_select.on_selection_changed(selection)

        image = QImage(4, 4, QImage.Format.Format_RGB32)
        image.fill(0)
        monkeypatch.setattr(feature.image_manager, "get_cropped_image", lambda: image)
        monkeypatch.setattr(
            feature.image_manager,
            "get_cropped_image_bytes",
            lambda: b"\x89PNG\r\n\x1a\nfake-image",
        )

        feature.handle_ocr_button()

        assert len(messages.calls) == 1
        kind, title, text = messages.calls[0]
        assert (kind, title) == ("critical", "OCR Error")
        assert "keyring" in text.lower()
        assert "API key storage is unavailable" in text
        assert feature.ocr_text.toPlainText() == ""

        assert feature.ocr_button.isEnabled()
        assert feature.translate_button.isEnabled()
        assert feature.progressbar.isHidden()
        assert feature.stop_button.isHidden()
        assert feature.findChildren(QThread) == []
        assert not hasattr(feature, "ocr_worker")
        # Fail fast: a cloud provider is never probed without a key.
        assert client_creations == []


def test_model_fetch_reports_a_storage_error_instead_of_crashing(no_keyring, monkeypatch):
    """A key-requiring provider still reports the storage failure, without a client."""
    client_creations = record_client_creation(monkeypatch)

    manager = ModelManager()
    try:
        manager.add(ProviderMeta("cloud", LLMProvider.OPENAI))
        errors: list[str] = []
        manager.error.connect(errors.append)

        manager.start_fetching_models("cloud")  # must not raise

        assert len(errors) == 1
        assert "cloud" in errors[0]
        assert "keyring" in errors[0].lower()
        # Fail fast: no keyless AnyLLM.create attempt for a cloud provider.
        assert client_creations == []
        # No half-created fetch worker/thread is left behind.
        assert manager.fetching_models_active_workers == []
    finally:
        manager.shutdown()


# --- keyless providers keep working while the keyring is down --------------


def test_keyless_model_fetch_keeps_working_while_keyring_is_unavailable(
    no_keyring, monkeypatch, wait_until
):
    """The banner promises keyless providers keep working: the fetch completes."""
    calls, client = keyless_client_factory(monkeypatch)

    manager = ModelManager()
    try:
        manager.add(ProviderMeta("ollama", LLMProvider.OLLAMA))
        errors: list[str] = []
        manager.error.connect(errors.append)
        loaded: list[None] = []
        manager.loaded_list_models.connect(lambda: loaded.append(None))

        manager.start_fetching_models("ollama")  # must not raise

        # The keyless client was built without a key, exactly once.
        assert calls == [(LLMProvider.OLLAMA, None, None)]
        assert wait_until(lambda: bool(loaded) or bool(errors))
        assert loaded, "the keyless model fetch must finish normally"
        assert errors == []
        assert client.list_models_calls == 1
    finally:
        manager.shutdown()


def test_translation_on_a_keyless_provider_is_not_blocked(
    no_keyring, fake_app, data_home, monkeypatch, wait_until
):
    """A local provider translates while the keyring is unavailable; no modal."""
    messages = RecordingMessageBox()
    monkeypatch.setattr(text_feature_module, "QMessageBox", messages)
    calls, _client = keyless_client_factory(monkeypatch)

    with open_window(fake_app) as window:
        feature = window.features[0]
        window.model.on_selection_changed(
            ModelSelection(provider="ollama", model="probe-model")
        )
        feature.orig_text.setPlainText("text for the local provider")

        feature.translate()

        # The worker path is reached (no storage abort) and the client is keyless.
        assert calls == [(LLMProvider.OLLAMA, None, None)]
        assert hasattr(feature, "worker")
        thread = feature._translation_thread

        assert wait_until(lambda: feature.translated_text.toPlainText() == "ok")
        assert wait_until(lambda: thread_stopped(thread))
        assert messages.calls == []
        # The normal completion path restored the tab (no storage modal).
        assert feature.translate_button.isEnabled()
        assert feature.progressbar.isHidden()
        assert feature.stop_button.isHidden()


def test_ocr_on_a_keyless_provider_is_not_blocked(
    no_keyring, fake_app, data_home, monkeypatch, wait_until
):
    """OCR keeps working for a local provider while the keyring is unavailable."""
    messages = RecordingMessageBox()
    monkeypatch.setattr(ocr_feature_module, "QMessageBox", messages)
    calls, _client = keyless_client_factory(monkeypatch)

    with open_window(fake_app) as window:
        feature = window.features[1]
        selection = ModelSelection(provider="ollama", model="vision-model")
        window.model.on_selection_changed(selection)
        feature.ocr_model_select.on_selection_changed(selection)

        image = QImage(4, 4, QImage.Format.Format_RGB32)
        image.fill(0)
        monkeypatch.setattr(feature.image_manager, "get_cropped_image", lambda: image)
        monkeypatch.setattr(
            feature.image_manager,
            "get_cropped_image_bytes",
            lambda: b"\x89PNG\r\n\x1a\nfake-image",
        )

        feature.handle_ocr_button()

        assert calls == [(LLMProvider.OLLAMA, None, None)]
        assert hasattr(feature, "ocr_worker")
        assert wait_until(lambda: feature.ocr_text.toPlainText() == "ok")
        assert wait_until(lambda: feature.findChildren(QThread) == [])
        assert messages.calls == []
        assert feature.ocr_button.isEnabled()


# --- the secret never reaches disk, QSettings, the cache or the logs --------


def test_aborted_save_never_persists_the_secret(
    no_keyring, fake_app, data_home, tmp_path, caplog, monkeypatch
):
    """A refused save leaves no copy of the key in any app-owned location."""
    messages = RecordingMessageBox()
    monkeypatch.setattr(provider_dialog_module, "QMessageBox", messages)
    # A unique token keeps the filesystem scan meaningful across the session.
    secret = f"sk-BAR11-FILE-LEAK-{uuid.uuid4().hex.upper()}"

    with (
        caplog.at_level(logging.DEBUG, logger="barbaros.security"),
        caplog.at_level(logging.DEBUG, logger="barbaros.model_manager"),
        open_window(fake_app) as window,
    ):
        dialog = ProviderDialog(window.model_manager, parent=window)
        try:
            assert apply_new_provider(dialog, name="acme", api_key=secret) is False
        finally:
            dialog.deleteLater()

        # Exercise the cache/save path in the same scope as the abort.
        model = Model.model_validate(
            {
                "id": "cached-after-abort",
                "created": 1_710_000_000,
                "object": "model",
                "owned_by": "tester",
            },
            strict=True,
        )
        window.model_manager.set_models("ollama", [model])

    assert any(record.name == "barbaros.security" for record in caplog.records)
    assert secret not in caplog.text

    # QSettings: the provider was not persisted and the file has no secret.
    fake_app.settings.sync()
    settings_path = Path(fake_app.settings.fileName())
    settings_bytes = settings_path.read_bytes() if settings_path.exists() else b""
    assert secret.encode() not in settings_bytes
    assert fake_app.settings.value("main_window/llm_providers") is None

    # Model cache bytes carry no secret.
    cache_path = data_home / "barbaros" / "models.json"
    assert cache_path.is_file()
    assert secret.encode() not in cache_path.read_bytes()

    # No plaintext/secret file anywhere under the redirected XDG directories.
    assert files_containing(secret, xdg_directories()) == []
    assert files_containing(secret, [tmp_path]) == []
