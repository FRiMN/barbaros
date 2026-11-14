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

import pytest
from PySide6 import __version__ as pyside_version

import barbaros
from barbaros.common import TARGET_LANGUAGES
from barbaros.features.ocr import OCRFeature
from barbaros.main_window import MainWindow
from barbaros.settings_sanitize import MAX_SETTINGS_BYTES
from barbaros.widgets.filterable_combobox import ModelSelection

APP_STARTUP_TIMEOUT_SECONDS = 120
STARTUP_RESULT_PREFIX = "STARTUP_RESULT "
PICKLE_MARKER = b"PySide::PyObjectWrapper"

# PySide6 >= 6.12 rejects pickled QSettings values; older versions unpickle
# them, so the BAR-28 fail-closed path (quarantine + memory settings) applies.
QT_REJECTS_PICKLED_OBJECTS = tuple(
    int(part) for part in pyside_version.split(".")[:2]
) >= (6, 12)


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
        "settings_filepath": app.settings.fileName(),
    }
    print("STARTUP_RESULT " + json.dumps(result))
    app.settings.sync()
    window.model_manager.shutdown()
    '''
)


# Simulates the PySide6 < 6.12 Flatpak runtime (BAR-28) on a PySide6 that is
# actually safe: the version gate only changes *our* decision, not Qt's parser.
UNSAFE_PYSIDE_PRELUDE = (
    "\nimport barbaros.settings_sanitize as _settings_sanitize\n"
    "\n_settings_sanitize.pyside_rejects_pickled_values = lambda: False\n"
)


def run_app_startup(
    config_home: Path,
    tmp_path: Path,
    *,
    expect_warning: str | None = None,
    unsafe_pyside: bool = False,
) -> dict:
    """Run the real ``App`` in a subprocess and return the state it printed.

    ``unsafe_pyside`` makes the version gate behave like PySide6 < 6.12.
    """
    prelude = UNSAFE_PYSIDE_PRELUDE if unsafe_pyside else ""
    script_text = APP_STARTUP_SCRIPT
    if prelude:
        marker = "import barbaros.main as barbaros_main\n"
        script_text = script_text.replace(marker, marker + prelude, 1)
        assert prelude in script_text
    script = tmp_path / "app_startup.py"
    script.write_text(script_text, encoding="utf-8")

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


@pytest.mark.skipif(
    not QT_REJECTS_PICKLED_OBJECTS,
    reason="PySide6 < 6.12 takes the BAR-28 fail-closed path "
    "(quarantine + memory settings) instead of the migration path",
)
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


@pytest.mark.skipif(
    not QT_REJECTS_PICKLED_OBJECTS,
    reason="PySide6 < 6.12 takes the BAR-28 fail-closed path "
    "(quarantine + memory settings) instead of the migration path",
)
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


@pytest.mark.skipif(
    not QT_REJECTS_PICKLED_OBJECTS,
    reason="PySide6 < 6.12 takes the BAR-28 fail-closed path "
    "(quarantine + memory settings) instead of the migration path",
)
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


# --- BAR-28: fail-closed startup on a PySide6 that unpickles -----------------
#
# ``unsafe_pyside=True`` patches only the version gate: the running Qt stays
# safe, so these tests exercise *our* decision, not Qt's parser.  The real old
# runtime is covered by test_legacy_pickled_config_is_quarantined_on_old_pyside
# and by the opt-in Flatpak test (tests/system/test_flatpak_pyside.py).


def quarantine_files(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.unsafe-*"))


def oversized_config(legacy_pickled_config: bytes) -> bytes:
    return legacy_pickled_config + b" " * MAX_SETTINGS_BYTES


HOSTILE_CONFIG_SCRIPT = textwrap.dedent(
    '''
    """Write a QSettings file whose pickled value would run code if unpickled."""

    import sys

    from PySide6.QtCore import QSettings


    class Payload:
        def __init__(self, marker):
            self.marker = marker

        def __reduce__(self):
            return (open, (self.marker, "w"))


    path, marker = sys.argv[1], sys.argv[2]
    settings = QSettings(path, QSettings.Format.IniFormat)
    settings.setValue("main_window/model", Payload(marker))
    settings.setValue("main_window/target_language", "ru")
    settings.sync()
    '''
)


def write_hostile_config(path: Path, marker: Path) -> None:
    """Create a config whose legacy value executes on an old-PySide unpickle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    script = path.parent / "write_hostile_config.py"
    script.write_text(HOSTILE_CONFIG_SCRIPT, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(script), str(path), str(marker)],
        capture_output=True,
        text=True,
        timeout=APP_STARTUP_TIMEOUT_SECONDS,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_unsafe_pyside_quarantines_oversized_config(tmp_path, legacy_pickled_config):
    config_home = tmp_path / "xdg-config"
    path = settings_path(config_home)
    path.parent.mkdir(parents=True)
    payload = oversized_config(legacy_pickled_config)
    path.write_bytes(payload)

    state = run_app_startup(
        config_home, tmp_path, unsafe_pyside=True, expect_warning="was moved to"
    )

    # The file never reaches QSettings: the app starts with defaults and keeps
    # its settings in memory for this session.
    assert state["target_languages"] == TARGET_LANGUAGES
    assert state["selected_model"] is None
    assert state["settings_filepath"] == ""
    assert not os.path.lexists(path)
    quarantined = quarantine_files(path)
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == payload


def test_unsafe_pyside_quarantines_symlinked_config(tmp_path, legacy_pickled_config):
    config_home = tmp_path / "xdg-config"
    link = settings_path(config_home)
    link.parent.mkdir(parents=True)
    target = tmp_path / "dotfiles" / "barbaros.conf"
    target.parent.mkdir(parents=True)
    target.write_bytes(legacy_pickled_config)
    link.symlink_to(target)

    state = run_app_startup(
        config_home, tmp_path, unsafe_pyside=True, expect_warning="was moved to"
    )

    assert not os.path.lexists(link)
    assert target.read_bytes() == legacy_pickled_config
    assert state["target_languages"] == TARGET_LANGUAGES
    assert state["settings_filepath"] == ""
    quarantined = quarantine_files(link)
    assert len(quarantined) == 1
    assert quarantined[0].is_symlink()


def test_unsafe_pyside_uses_memory_for_read_only_config_dir(
    tmp_path, legacy_pickled_config
):
    config_home = tmp_path / "xdg-config"
    path = settings_path(config_home)
    path.parent.mkdir(parents=True)
    path.write_bytes(legacy_pickled_config)
    path.parent.chmod(0o500)
    try:
        state = run_app_startup(
            config_home,
            tmp_path,
            unsafe_pyside=True,
            expect_warning="kept in memory for this session",
        )
    finally:
        path.parent.chmod(0o700)

    # The file could not be moved aside, but it is never read either.
    assert path.read_bytes() == legacy_pickled_config
    assert state["target_languages"] == TARGET_LANGUAGES
    assert state["selected_model"] is None
    assert state["settings_filepath"] == ""


def test_unsafe_pyside_sanitizes_a_small_hostile_pickle(tmp_path):
    """A payload that would execute on PySide6 6.11 is never read.

    On the safe PySide6 used by the test suite the marker assertion is
    trivially true; it becomes a real regression guard when the suite runs on an
    old runtime (Flatpak build/test environments).
    """
    config_home = tmp_path / "xdg-config"
    path = settings_path(config_home)
    marker = tmp_path / "pwned"
    write_hostile_config(path, marker)
    assert PICKLE_MARKER in path.read_bytes()

    run_app_startup(
        config_home, tmp_path, unsafe_pyside=True, expect_warning="was moved to"
    )

    assert not marker.exists()
    assert not os.path.lexists(path)
    assert PICKLE_MARKER in quarantine_files(path)[0].read_bytes()


def test_unsafe_pyside_quarantines_a_hostile_oversized_pickle(tmp_path):
    """The same payload above the size cap is moved aside and never read."""
    config_home = tmp_path / "xdg-config"
    path = settings_path(config_home)
    marker = tmp_path / "pwned"
    write_hostile_config(path, marker)
    path.write_bytes(path.read_bytes() + b" " * MAX_SETTINGS_BYTES)

    run_app_startup(
        config_home, tmp_path, unsafe_pyside=True, expect_warning="was moved to"
    )

    assert not marker.exists()
    assert not os.path.lexists(path)
    quarantined = quarantine_files(path)
    assert len(quarantined) == 1
    assert PICKLE_MARKER in quarantined[0].read_bytes()


@pytest.mark.skipif(
    not QT_REJECTS_PICKLED_OBJECTS,
    reason="PySide6 < 6.12 unpickles QSettings values instead of rejecting them",
)
def test_oversized_config_is_left_alone_on_safe_pyside(
    tmp_path, legacy_pickled_config
):
    """On PySide6 >= 6.12 an unclean file is harmless: keep the preferences."""
    config_home = tmp_path / "xdg-config"
    path = settings_path(config_home)
    path.parent.mkdir(parents=True)
    payload = oversized_config(legacy_pickled_config)
    path.write_bytes(payload)

    state = run_app_startup(
        config_home,
        tmp_path,
        expect_warning="could not sanitize the settings file",
    )

    # Qt may rewrite the file when the app syncs, but nothing is moved and no
    # quarantine appears: on >= 6.12 an unclean file is not dangerous.
    data = path.read_bytes()
    assert b"target_language=ru" in data
    assert b"\n[main_window]" not in data  # still one INI document, not appended
    assert state["settings_filepath"] == str(path)
    assert not quarantine_files(path)


@pytest.mark.skipif(
    QT_REJECTS_PICKLED_OBJECTS,
    reason="PySide6 >= 6.12 sanitizes and migrates pickled settings instead of "
    "taking the BAR-28 fail-closed path",
)
def test_legacy_pickled_config_is_quarantined_on_old_pyside(
    tmp_path, legacy_pickled_config
):
    """On the real PySide6 < 6.12 runtime the fail-closed path must hold.

    The file is never read (unpickling it would execute the payload), so the
    whole file is moved aside and the app starts on defaults kept in memory.
    Unlike the ``unsafe_pyside=True`` tests, this runs the real old runtime.
    """
    config_home = tmp_path / "xdg-config"
    path = settings_path(config_home)
    path.parent.mkdir(parents=True)
    path.write_bytes(legacy_pickled_config)

    state = run_app_startup(config_home, tmp_path, expect_warning="was moved to")

    assert state["target_languages"] == TARGET_LANGUAGES
    assert state["selected_model"] is None
    assert state["settings_filepath"] == ""
    assert not os.path.lexists(path)
    quarantined = quarantine_files(path)
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == legacy_pickled_config


def test_unsafe_pyside_keeps_settings_in_memory(tmp_path):
    """On an old runtime nothing is persisted: the app still starts."""
    config_home = tmp_path / "xdg-config"

    state = run_app_startup(
        config_home,
        tmp_path,
        unsafe_pyside=True,
        expect_warning="settings are kept in memory for this session",
    )

    assert state["settings_filepath"] == ""
    assert state["selected_model"] is None


def test_unsafe_pyside_does_not_trust_an_escaped_variant(
    tmp_path, legacy_pickled_config
):
    """Qt unescapes the INI before it parses the variant: never read the file.

    ``\\x40Variant(`` / ``PyObject\\x57rapper`` are invisible to the raw-byte
    scan but are still unpickled by PySide6 < 6.12, so the fail-closed path must
    not depend on the scan at all (BAR-28).
    """
    escaped = legacy_pickled_config.replace(
        b"=@Variant(", b"=\\x40Variant("
    ).replace(b"PySide::PyObjectWrapper", b"PySide::PyObject\\x57rapper")
    config_home = tmp_path / "xdg-config"
    path = settings_path(config_home)
    path.parent.mkdir(parents=True)
    path.write_bytes(escaped)

    state = run_app_startup(
        config_home, tmp_path, unsafe_pyside=True, expect_warning="was moved to"
    )

    assert state["target_languages"] == TARGET_LANGUAGES
    assert state["settings_filepath"] == ""
    assert not os.path.lexists(path)
    quarantined = quarantine_files(path)
    assert len(quarantined) == 1
    assert b"\\x40Variant(" in quarantined[0].read_bytes()
