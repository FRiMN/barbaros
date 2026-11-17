"""System tests for the Settings -> Providers card following manager changes (issue #3).

``ProvidersCard`` renders a snapshot of ``ModelManager``, so the "models are not
loaded" warning icon used to survive a successful fetch: only the top-bar model
selector subscribed to the manager's signals.  The card must follow both kinds
of change without the **Manage Providers** dialog being opened and closed:

* a model list arriving after the card was built (the per-provider reload
  button, a background fetch) - the warning icon disappears;
* a provider added, edited or removed through the manager - the card list is
  rebuilt.

Every test drives the real composition root (``MainWindow`` + ``ModelManager``,
offscreen Qt); only the keyring backend and the XDG directories are substituted
by the session fixtures.  The warning icon is located by its tooltip and the
provider card through the feature tree, so the tests do not depend on
``ProvidersCard`` internals (no importing it, no calling ``refresh()``).
"""

from __future__ import annotations

import contextlib

from any_llm import LLMProvider
from any_llm.types.model import Model
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLabel

from barbaros.main_window import MainWindow
from barbaros.model_manager import ProviderMeta

# --- helpers ---------------------------------------------------------------


@contextlib.contextmanager
def open_window(app):
    """Build ``MainWindow`` and always stop its workers and release the window."""
    window = MainWindow(app=app)
    try:
        yield window
    finally:
        window.model_manager.shutdown()
        window.deleteLater()


def providers_card(window: MainWindow):
    """The ``ProvidersCard`` mounted in the Settings tab, without importing it."""
    for feature in window.features:
        group = getattr(feature, "providers_group", None)
        if group is not None:
            return group.providers_card
    raise AssertionError("ProvidersCard is not part of the MainWindow")


def warning_icons(card) -> list[QLabel]:
    """The "models are not loaded" icons: labels that carry a tooltip."""
    return [label for label in card.findChildren(QLabel) if label.toolTip()]


def flush_deferred_deletes() -> None:
    """Destroy the cards ``refresh()`` scheduled for deletion.

    The card rebuilds with ``deleteLater()``, so the replaced labels stay
    children of the card - and stay findable by ``findChildren`` - until the
    deferred-delete events are processed.  Without this the assertions would
    observe both the old and the new card.
    """
    application = QApplication.instance()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def models(*ids: str) -> list[Model]:
    """Fetched models in the shape ``ModelManager.set_models`` accepts."""
    return [
        Model(id=model_id, created=1_710_000_000, object="model", owned_by="tester")
        for model_id in ids
    ]


# --- model list arrives after the card was built ---------------------------


def test_warning_icon_cleared_after_successful_fetch(qapp, fake_app, data_home):
    """A completed fetch updates the card: the warning icon disappears (issue #3)."""
    with open_window(fake_app) as window:
        card = providers_card(window)
        flush_deferred_deletes()

        # A fresh provider has no models yet, so the card warns.
        assert len(warning_icons(card)) == 1

        window.model_manager.set_models("ollama", models("llama3"))
        flush_deferred_deletes()

        assert warning_icons(card) == []


def test_warning_icon_returns_when_fetch_returns_empty_list(qapp, fake_app, data_home):
    """An empty list is still "models are not loaded" - the icon must come back.

    The icon is driven by the current model list, not by "a fetch happened":
    a successful fetch that returns nothing leaves the provider unusable.
    """
    with open_window(fake_app) as window:
        card = providers_card(window)

        window.model_manager.set_models("ollama", models("llama3"))
        flush_deferred_deletes()
        assert warning_icons(card) == []

        window.model_manager.set_models("ollama", [])
        flush_deferred_deletes()

        assert len(warning_icons(card)) == 1


def test_warning_icons_track_each_provider_model_list(qapp, fake_app, data_home):
    """One warning icon per provider with an empty list, updated per fetch."""
    with open_window(fake_app) as window:
        card = providers_card(window)

        window.model_manager.add(ProviderMeta("second", LLMProvider.OLLAMA))
        flush_deferred_deletes()
        assert len(warning_icons(card)) == 2

        window.model_manager.set_models("second", models("second-1"))
        flush_deferred_deletes()
        assert len(warning_icons(card)) == 1

        window.model_manager.set_models("ollama", models("llama3"))
        flush_deferred_deletes()
        assert warning_icons(card) == []


# --- provider list changes -------------------------------------------------


def test_provider_add_and_remove_rebuild_the_card(qapp, fake_app, data_home):
    """Adding and removing a provider through the manager rebuilds the cards."""
    with open_window(fake_app) as window:
        card = providers_card(window)
        assert len(window.model_manager) == 1

        window.model_manager.add(ProviderMeta("second", LLMProvider.OLLAMA))
        flush_deferred_deletes()

        assert len(window.model_manager) == 2
        assert len(warning_icons(card)) == 2

        window.model_manager.remove("second")
        flush_deferred_deletes()

        assert len(window.model_manager) == 1
        assert len(warning_icons(card)) == 1


def test_provider_edit_rebuilds_the_card(qapp, fake_app, data_home):
    """Editing a provider replaces it with an empty model list - the card follows."""
    with open_window(fake_app) as window:
        card = providers_card(window)

        window.model_manager.set_models("ollama", models("llama3"))
        flush_deferred_deletes()
        assert warning_icons(card) == []

        window.model_manager.update(ProviderMeta("ollama", LLMProvider.OLLAMA))
        flush_deferred_deletes()

        # The edited provider is a new ProviderClient: its list starts empty.
        assert window.model_manager["ollama"].models == []
        assert len(warning_icons(card)) == 1
