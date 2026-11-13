"""System tests for the BAR-01 migration away from pickled QSettings values.

Two layers are covered:

* the real ``App`` in a subprocess, started on a config file that PySide6 6.12
  cannot read - the crash reported after the dependency update - including the
  fail-safe path with an unsanitizable (symlinked) config;
* ``MainWindow`` in-process, checking that model selections are persisted as
  JSON and restored, can be cleared, and that malformed (including deeply
  nested) JSON does not break startup.

``App`` cannot be constructed in-process (QApplication is a singleton owned by
the session ``qapp`` fixture), hence the generated startup script.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path

import barbaros
from barbaros.features.ocr import OCRFeature
from barbaros.main_window import MainWindow
from barbaros.widgets.filterable_combobox import ModelSelection

APP_STARTUP_TIMEOUT_SECONDS = 120
STARTUP_RESULT_PREFIX = "STARTUP_RESULT "
PICKLE_MARKER = b"PySide::PyObjectWrapper"


# --- helpers ---------------------------------------------------------------


def settings_path(config_home: Path) -> Path:
    """The user-scope INI file for the application identity used by ``App``."""
    return config_home / "io.github.frimn" / "barbaros.conf"


def backup_files(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.bak-*"))


@contextmanager
def opened_window(app):
    """Construct ``MainWindow``; always stop its workers and release the window."""
    window = MainWindow(app=app)
    try:
        yield window
    finally:
        window.model_manager.shutdown()
        window.deleteLater()


def ocr_feature(window: MainWindow) -> OCRFeature:
    return next(feature for feature in window.features if isinstance(feature, OCRFeature))


APP_STARTUP_SCRIPT = textwrap.dedent(
    '''
    """Start the real ``App`` with the tray stubbed out; print its state."""

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
    window = app.main_window
    selection = window.model.selected_item
    result = {
        "target_languages": window.target_language_list,
        "selected_model": None if selection is None else selection.to_dict(),
    }
    print("STARTUP_RESULT " + json.dumps(result))
    app.settings.sync()
    window.model_manager.shutdown()
    '''
)


def run_app_startup(
    config_home: Path, tmp_path: Path, *, expect_warning: str | None = None
) -> dict:
    """Run the real ``App`` in a subprocess and return the state it printed."""
    script = tmp_path / "app_startup.py"
    script.write_text(APP_STARTUP_SCRIPT, encoding="utf-8")

    env = os.environ.copy()
    # Everything is redirected into the test's tmp dir: no real XDG dirs.
    env["XDG_CONFIG_HOME"] = str(config_home)
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg-data")
    env["XDG_CACHE_HOME"] = str(tmp_path / "xdg-cache")
    # Hermetic: do not register the DBus service and do not depend on the
    # developer's display or PYTHONPATH.
    env["DBUS_SESSION_BUS_ADDRESS"] = "disabled:"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(Path(barbaros.__file__).resolve().parent.parent)

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
    # The computed config path must be the one QSettings actually uses, or the
    # migration would silently target a different file.
    assert "do not match the sanitized one" not in completed.stdout, completed.stdout
    if expect_warning is not None:
        assert expect_warning in completed.stdout, completed.stdout

    results = [
        line[len(STARTUP_RESULT_PREFIX) :]
        for line in completed.stdout.splitlines()
        if line.startswith(STARTUP_RESULT_PREFIX)
    ]
    assert len(results) == 1, f"startup result not found in output:\n{completed.stdout}"
    return json.loads(results[0])


# --- App startup with a legacy config ---------------------------------------


def test_app_starts_with_legacy_pickled_settings(
    tmp_path, legacy_pickled_config
):
    """The reported crash: a config with pickled values must not block startup.

    The legacy selection is not migrated (a rejected pickle cannot be read
    safely); the rest of the file must survive and the pickled lines must be
    gone with a backup left next to the config.
    """
    config_home = tmp_path / "xdg-config"
    path = settings_path(config_home)
    path.parent.mkdir(parents=True)
    path.write_bytes(legacy_pickled_config)

    state = run_app_startup(config_home, tmp_path)

    # Valid neighbours were read, the unreadable legacy selection fell back.
    assert state["target_languages"] == ["ar", "de", "en", "ru"]
    assert state["selected_model"] is None

    data = path.read_bytes()
    assert PICKLE_MARKER not in data
    assert b"target_language=ru" in data
    backups = backup_files(path)
    assert len(backups) == 1
    assert backups[0].read_bytes() == legacy_pickled_config


def test_app_starts_again_after_the_migration(tmp_path, legacy_pickled_config):
    """A second start is a normal start: no pickle, no second backup."""
    config_home = tmp_path / "xdg-config"
    path = settings_path(config_home)
    path.parent.mkdir(parents=True)
    path.write_bytes(legacy_pickled_config)

    first = run_app_startup(config_home, tmp_path)
    second = run_app_startup(config_home, tmp_path)

    assert first == second
    assert PICKLE_MARKER not in path.read_bytes()
    assert len(backup_files(path)) == 1


def test_app_starts_with_symlinked_config(tmp_path, legacy_pickled_config):
    """A dotfiles-style symlink cannot be sanitized; the read guard keeps startup.

    The raw-file reader refuses to follow the link, so the pickle stays and the
    QSettings crash is prevented only by ``read_setting``.  The neighbour
    values must still be recovered (that is the retry), and only the poisoned
    selection falls back to the default.
    """
    config_home = tmp_path / "xdg-config"
    link = settings_path(config_home)
    link.parent.mkdir(parents=True)
    target = tmp_path / "dotfiles" / "barbaros.conf"
    target.parent.mkdir(parents=True)
    target.write_bytes(legacy_pickled_config)
    link.symlink_to(target)

    state = run_app_startup(
        config_home, tmp_path, expect_warning="could not sanitize the settings file"
    )

    assert state["target_languages"] == ["ar", "de", "en", "ru"]
    assert state["selected_model"] is None


# --- model selections are stored as JSON -----------------------------------


def test_model_selection_is_persisted_as_json(fake_app, fake_settings):
    selection = ModelSelection(provider="ollama", model="llama3")

    with opened_window(fake_app) as window:
        window.save_choosed_model(selection)
        fake_settings.sync()

    assert PICKLE_MARKER not in Path(fake_settings.fileName()).read_bytes()
    stored = fake_settings.value("main_window/model")
    assert isinstance(stored, str)
    assert json.loads(stored) == {"provider": "ollama", "model": "llama3"}

    # A restarted window restores the selection from the JSON value.
    with opened_window(fake_app) as window:
        assert window.model.selected_item == selection


def test_ocr_model_selection_is_persisted_as_json(fake_app, fake_settings):
    selection = ModelSelection(provider="ollama", model="vision-1")

    with opened_window(fake_app) as window:
        ocr_feature(window).save_choosed_ocr_model(selection)
        fake_settings.sync()

    stored = fake_settings.value("ocr_feature/model")
    assert isinstance(stored, str)
    assert json.loads(stored) == {"provider": "ollama", "model": "vision-1"}

    with opened_window(fake_app) as window:
        assert ocr_feature(window).ocr_model_select.selected_item == selection


def test_malformed_model_setting_is_ignored(fake_app, fake_settings):
    # Deeply nested JSON makes json.loads raise RecursionError, a RuntimeError
    # subclass: it must be treated like any other corruption, not abort startup.
    fake_settings.setValue("main_window/model", "[" * 5000 + "]" * 5000)
    fake_settings.setValue("ocr_feature/model", '{"provider": null}')
    fake_settings.sync()

    with opened_window(fake_app) as window:
        assert window.model.selected_item is None
        assert ocr_feature(window).ocr_model_select.selected_item is None


def test_clearing_model_selection_removes_json_setting(fake_app, fake_settings):
    selection = ModelSelection(provider="ollama", model="llama3")

    with opened_window(fake_app) as window:
        window.save_choosed_model(selection)
        fake_settings.sync()
        assert fake_settings.contains("main_window/model")

        # The selector can legitimately emit None (no selection); the slot must
        # clear the setting instead of crashing on ``None.to_dict()``.
        window.model.on_selection_changed(None)
        fake_settings.sync()

        assert not fake_settings.contains("main_window/model")

    with opened_window(fake_app) as window:
        feature = ocr_feature(window)
        feature.save_choosed_ocr_model(selection)
        fake_settings.sync()
        assert fake_settings.contains("ocr_feature/model")

        feature.ocr_model_select.on_selection_changed(None)
        fake_settings.sync()

        assert not fake_settings.contains("ocr_feature/model")
