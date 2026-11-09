"""System tests for the model-list cache flow (docs/model-cache-storage.md §7.2).

Every test drives the real composition root (``MainWindow.__init__`` / ``App``)
and the real ``ModelCacheStore``; only the disk location is redirected, so no
test touches the developer's home, config, or keyring.  Item numbers in the
docstrings refer to the "Integration/system" matrix in §7.2 of the plan.

``App`` cannot be constructed in-process (QApplication is a singleton owned by
the session ``qapp`` fixture), so the two ``App`` startup tests run a generated
script in a subprocess instead.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path

import pytest
from any_llm.types.model import Model

from barbaros.main_window import MainWindow
from barbaros.model_cache import SETTINGS_KEY
from barbaros.model_manager import ModelManager
from barbaros.widgets.filterable_combobox import ModelSelection

OVERSIZED_CACHE_BYTES = 4 * 1024 * 1024
APP_STARTUP_TIMEOUT_SECONDS = 120
STARTUP_RESULT_PREFIX = "STARTUP_RESULT "


# --- helpers ---------------------------------------------------------------


def cache_path(data_home: Path) -> Path:
    """Default cache file for the application name set by the ``qapp`` fixture."""
    return Path(data_home) / "barbaros" / "models.json"


def write_raw(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def as_models(entries: list[dict]) -> list[Model]:
    """Turn cache-entry dicts into the ``Model`` objects ``set_models`` expects."""
    return [Model.model_validate(entry) for entry in entries]


@contextmanager
def opened_window(app):
    """Construct ``MainWindow``; always stop its workers and release the window."""
    window = MainWindow(app=app)
    try:
        yield window
    finally:
        window.model_manager.shutdown()
        window.deleteLater()


def restored_ids(window: MainWindow, provider: str = "ollama") -> list[str]:
    return [model.id for model in window.model_manager[provider].models]


def selector_providers(window: MainWindow) -> list[str]:
    """Provider names shown in the model-selector popup tree."""
    tree = window.model.filterable_popup.tree_widget
    return [
        tree.topLevelItem(index).text(0) for index in range(tree.topLevelItemCount())
    ]


def selector_models(window: MainWindow, provider: str) -> list[str] | None:
    """Model ids shown under ``provider`` in the model-selector popup tree."""
    tree = window.model.filterable_popup.tree_widget
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item.text(0) == provider:
            return [item.child(position).text(0) for position in range(item.childCount())]
    return None


# --- §7.2 item 1: corrupt cache --------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b'{"version": 1, "models": {"ollama": [{"id": "m1"', id="truncated-json"),
        pytest.param(b"\xff\xfe\x00not a json document", id="garbage-bytes"),
        pytest.param(b'[{"version": 1, "models": {}}]', id="top-level-list"),
        pytest.param(
            b'{"version": 1, "models": {}}' + b" " * OVERSIZED_CACHE_BYTES,
            id="oversized",
        ),
    ],
)
def test_corrupt_cache_starts_with_empty_models(payload, data_home, fake_app):
    """A bad cache file never blocks startup: providers load, models stay empty."""
    path = cache_path(data_home)
    write_raw(path, payload)

    with opened_window(fake_app) as window:
        assert "ollama" in window.model_manager
        assert all(not client.models for client in window.model_manager.values())

    # The bad file is kept for inspection; the next successful save replaces it.
    assert path.is_file()


# --- §7.2 item 2: valid cache restored -------------------------------------


def test_valid_cache_is_restored_and_visible_in_selector(
    data_home, fake_app, make_models, cache_doc, write_cache
):
    entries = make_models(3)
    expected_ids = [entry["id"] for entry in entries]
    write_cache(cache_path(data_home), cache_doc({"ollama": entries}))

    with opened_window(fake_app) as window:
        assert restored_ids(window) == expected_ids
        assert all(
            isinstance(model, Model) for model in window.model_manager["ollama"].models
        )
        assert selector_models(window, "ollama") == expected_ids
        assert window.model.has_item(
            ModelSelection(provider="ollama", model=expected_ids[0])
        )
        assert not window.model.has_item(
            ModelSelection(provider="ollama", model="not-cached")
        )


# --- §7.2 item 3: unknown provider record ----------------------------------


def test_cache_record_for_unknown_provider_is_ignored(
    data_home, fake_app, make_models, cache_doc, write_cache
):
    known = make_models(2, prefix="known")
    unknown = make_models(2, prefix="ghost")
    write_cache(
        cache_path(data_home), cache_doc({"ghost-provider": unknown, "ollama": known})
    )

    with opened_window(fake_app) as window:
        # The cache does not create providers: only the configured one exists.
        assert "ghost-provider" not in window.model_manager
        assert set(window.model_manager) == {"ollama"}
        assert restored_ids(window) == [entry["id"] for entry in known]
        assert selector_providers(window) == ["ollama"]


# --- §7.2 item 4: restart --------------------------------------------------


def test_models_are_restored_after_restart(
    data_home, fake_app, make_models, cache_doc
):
    path = cache_path(data_home)
    entries = make_models(2)
    expected_ids = [entry["id"] for entry in entries]

    with opened_window(fake_app) as first:
        assert not path.exists()  # an empty cache is not written on startup
        first.model_manager.set_models("ollama", as_models(entries))

    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == cache_doc(
        {"ollama": entries}
    )

    # "Restart": a new window resolves the same default path and restores them.
    with opened_window(fake_app) as second:
        assert restored_ids(second) == expected_ids
        assert selector_models(second, "ollama") == expected_ids


# --- §7.2 item 5: legacy QSettings key -------------------------------------


def test_legacy_cache_key_is_removed_without_migration(
    data_home,
    fake_app,
    fake_settings,
    make_models,
    cache_doc,
):
    path = cache_path(data_home)
    providers_json = json.dumps(
        [provider.to_dict() for provider in ModelManager.default_providers()]
    )
    legacy_json = json.dumps(
        {
            "legacy-provider": [
                {
                    "id": "legacy-model",
                    "created": 1_600_000_000,
                    "object": "model",
                    "owned_by": "legacy",
                }
            ]
        }
    )
    fake_settings.setValue("main_window/llm_by_providers", legacy_json)
    fake_settings.setValue("main_window/llm_providers", providers_json)
    fake_settings.setValue("main_window/target_language_list", "en,de")
    fake_settings.sync()

    with opened_window(fake_app) as window:
        assert not fake_settings.contains("main_window/llm_by_providers")
        assert fake_settings.contains("main_window/llm_providers")
        assert fake_settings.value("main_window/llm_providers") == providers_json
        assert fake_settings.value("main_window/target_language_list") == "en,de"
        assert window.target_language_list == ["en", "de"]

        # Nothing is migrated: startup does not write the new cache file at all.
        assert not path.exists()

        window.model_manager.set_models("ollama", as_models(make_models(1, prefix="fresh")))
        # A cache write still does not resurrect the legacy key.
        assert not fake_settings.contains("main_window/llm_by_providers")

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document == cache_doc({"ollama": make_models(1, prefix="fresh")})
    assert "legacy-provider" not in document["models"]


# --- §7.2 item 6: App() startup (subprocess) -------------------------------

APP_STARTUP_SCRIPT = textwrap.dedent(
    '''
    """Start the real ``App`` with the tray icon stubbed out; print its state."""

    import json

    import keyring
    from keyring.backend import KeyringBackend


    class MemoryKeyring(KeyringBackend):
        priority = 1

        def __init__(self):
            self.passwords = {}

        def get_password(self, service, username):
            return self.passwords.get((service, username))

        def set_password(self, service, username, password):
            self.passwords[(service, username)] = password

        def delete_password(self, service, username):
            self.passwords.pop((service, username), None)


    # Must happen before barbaros.main: App builds widgets that read keyring.
    keyring.set_keyring(MemoryKeyring())

    import barbaros.main as barbaros_main

    # The tray icon needs a desktop system tray, absent under offscreen Qt.
    barbaros_main.TrayIcon = lambda app: None

    app = barbaros_main.App(["barbaros"])
    manager = app.main_window.model_manager
    result = {
        "providers": sorted(manager.keys()),
        "models": {name: [model.id for model in manager[name].models] for name in manager},
    }
    print("STARTUP_RESULT " + json.dumps(result))
    manager.shutdown()
    '''
)


def run_app_startup(data_home: Path, tmp_path: Path) -> dict:
    """Run the real ``App`` in a subprocess and return the state it printed."""
    script = tmp_path / "app_startup.py"
    script.write_text(APP_STARTUP_SCRIPT, encoding="utf-8")

    env = os.environ.copy()
    # Everything is redirected into the test's tmp dir: no real XDG dirs.
    env["XDG_DATA_HOME"] = str(data_home)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg-config")
    env["XDG_CACHE_HOME"] = str(tmp_path / "xdg-cache")
    # Hermetic: do not register the DBus service if the developer runs the app.
    env["DBUS_SESSION_BUS_ADDRESS"] = "disabled:"

    completed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=APP_STARTUP_TIMEOUT_SECONDS,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Traceback (most recent call last)" not in completed.stderr, completed.stderr

    results = [
        line[len(STARTUP_RESULT_PREFIX) :]
        for line in completed.stdout.splitlines()
        if line.startswith(STARTUP_RESULT_PREFIX)
    ]
    assert len(results) == 1, f"startup result not found in output:\n{completed.stdout}"
    return json.loads(results[0])


def test_app_startup_with_corrupt_cache(data_home, tmp_path):
    """§7.2 item 6a: the full ``App`` starts even when the cache is corrupt."""
    write_raw(cache_path(data_home), b'{"version": 1, "models": {"ollama": [')

    state = run_app_startup(data_home, tmp_path)

    assert state["providers"] == ["ollama"]
    assert state["models"] == {"ollama": []}


def test_app_startup_restores_cached_models(
    data_home, tmp_path, make_models, cache_doc, write_cache
):
    """§7.2 item 6b: the full ``App`` restores models from a valid cache."""
    entries = make_models(2)
    write_cache(cache_path(data_home), cache_doc({"ollama": entries}))

    state = run_app_startup(data_home, tmp_path)

    assert state["providers"] == ["ollama"]
    assert state["models"]["ollama"] == [entry["id"] for entry in entries]


# --- §7.2 item 7: Flatpak-like data home -----------------------------------


def test_flatpak_like_data_home_is_the_only_write_location(
    tmp_path, monkeypatch, fake_app, make_models, cache_doc
):
    app_data = tmp_path / ".var" / "app" / "io.github.frimn.barbaros" / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(app_data))
    entries = make_models(2)
    expected = app_data / "barbaros" / "models.json"

    from PySide6.QtCore import QStandardPaths

    resolved = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    assert Path(resolved) == app_data / "barbaros"

    with opened_window(fake_app) as window:
        assert not expected.exists()
        window.model_manager.set_models("ollama", as_models(entries))

    assert expected.is_file()
    assert json.loads(expected.read_text(encoding="utf-8")) == cache_doc(
        {"ollama": entries}
    )

    # Nothing is written outside the sandbox data dir (the test's explicit
    # QSettings file lives in tmp_path and is managed by ``fake_settings``).
    stray_files = [
        file
        for file in tmp_path.rglob("*")
        if file.is_file() and file != expected and file.name != "settings.ini"
    ]
    assert stray_files == []

    # The Flatpak app-data root has no sibling writes either.
    assert [child.name for child in app_data.iterdir()] == ["barbaros"]
    assert [child.name for child in (app_data / "barbaros").iterdir()] == [
        "models.json"
    ]


# --- §7.2 item 8: no network at startup ------------------------------------


def test_startup_performs_no_network_or_fetch(
    data_home,
    fake_app,
    monkeypatch,
    make_models,
    cache_doc,
    write_cache,
):
    create_calls: list[tuple] = []
    fetch_calls: list[str] = []

    def forbid_create(*args, **kwargs):
        create_calls.append((args, kwargs))
        raise AssertionError("startup must not create an LLM client")

    def record_fetch(self, provider):
        fetch_calls.append(provider.meta.name)

    monkeypatch.setattr("barbaros.model_manager.AnyLLM.create", forbid_create)
    # Replace only the worker-spawning step of the explicit reload path: the
    # test asserts *what triggers* a fetch without starting threads or network.
    monkeypatch.setattr(ModelManager, "_start_fetching_models", record_fetch)

    with opened_window(fake_app) as window:
        assert restored_ids(window) == []
        assert window.model_manager.fetching_models_active_workers == []

    entries = make_models(2)
    write_cache(cache_path(data_home), cache_doc({"ollama": entries}))
    with opened_window(fake_app) as window:
        # A valid cache is restored from disk only, still without any fetch.
        assert restored_ids(window) == [entry["id"] for entry in entries]
        assert window.model_manager.fetching_models_active_workers == []
        assert create_calls == []
        assert fetch_calls == []

        # An explicit "Reload models" action is what starts a fetch.
        window.model_manager.start_fetching_models()
        assert fetch_calls == ["ollama"]
        assert create_calls == []
        assert window.model_manager.fetching_models_active_workers == []

    assert fetch_calls == ["ollama"]  # nothing else triggered a fetch


# --- config override: model_cache_path -------------------------------------


def test_config_override_changes_cache_location_and_survives_restart(
    tmp_path, monkeypatch, fake_app, fake_settings, make_models
):
    """An absolute ``model_cache_path`` replaces the auto-resolved location."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    custom = tmp_path / "custom" / "models.json"
    fake_settings.setValue(SETTINGS_KEY, str(custom))
    fake_settings.sync()

    entries = make_models(2)
    with opened_window(fake_app) as window:
        window.model_manager.set_models("ollama", as_models(entries))

    assert custom.is_file()
    assert not cache_path(tmp_path / "xdg-data").exists()
    assert list(json.loads(custom.read_text())["models"]) == ["ollama"]

    # The override is read again on the next start, so models are restored.
    with opened_window(fake_app) as window:
        assert restored_ids(window) == [entry["id"] for entry in entries]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("relative/models.json", id="relative"),
        pytest.param("~no-such-user-xyz/models.json", id="unresolvable-tilde"),
        pytest.param("", id="empty"),
    ],
)
def test_invalid_config_override_falls_back_to_default(
    value, tmp_path, monkeypatch, fake_app, fake_settings, make_models
):
    """A bad override never breaks startup and never writes to the CWD."""
    data_home = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.chdir(tmp_path)
    fake_settings.setValue(SETTINGS_KEY, value)
    fake_settings.sync()

    with opened_window(fake_app) as window:
        window.model_manager.set_models("ollama", as_models(make_models(1)))

    assert cache_path(data_home).is_file()
    assert not (tmp_path / "relative").exists()
