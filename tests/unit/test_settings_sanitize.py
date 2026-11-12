"""Unit tests for the BAR-01 legacy-pickle sanitizer and the settings read guard.

The ``legacy_pickled_config`` fixture (tests/conftest.py) recreates what
PySide6 writes for ``QSettings.setValue`` with a Python object.  Under
PySide6 >= 6.12 Qt refuses to deserialize such values, so the tests that rely
on that refusal are skipped on older versions.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QByteArray, QSettings

from barbaros.common import SettingsProxy, read_setting
from barbaros.settings_sanitize import (
    MAX_SETTINGS_BYTES,
    PICKLE_MARKER,
    sanitize_pickled_settings,
    settings_file_path,
)


def pyside_major_minor() -> tuple[int, int]:
    parts = pyside_version.split(".")
    return int(parts[0]), int(parts[1])


QT_REJECTS_PICKLED_OBJECTS = pyside_major_minor() >= (6, 12)
rejects_legacy_pickle = pytest.mark.skipif(
    not QT_REJECTS_PICKLED_OBJECTS,
    reason="PySide6 < 6.12 unpickles QSettings values instead of rejecting them",
)


def write_config(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def backup_files(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.bak-*"))


# --- sanitizer ---------------------------------------------------------------


def test_legacy_pickle_is_removed_and_other_values_survive(
    tmp_path, legacy_pickled_config
):
    path = write_config(tmp_path / "barbaros.conf", legacy_pickled_config)

    assert sanitize_pickled_settings(path) == 2

    data = path.read_bytes()
    assert PICKLE_MARKER not in data
    # The pickled keys are gone, the neighbours are byte-identical.
    assert b"model=@Variant" not in data
    assert b"target_language=ru" in data
    assert b'target_language_list="ar,de,en,ru"' in data
    assert data.startswith(b"[main_window]\ngeometry=@ByteArray(")
    # A may-be-malicious value is never silently dropped: a backup is kept.
    backups = backup_files(path)
    assert len(backups) == 1
    assert backups[0].read_bytes() == legacy_pickled_config
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600


def test_second_run_is_a_noop_and_does_not_duplicate_the_backup(
    tmp_path, legacy_pickled_config
):
    path = write_config(tmp_path / "barbaros.conf", legacy_pickled_config)
    assert sanitize_pickled_settings(path) == 2
    sanitized = path.read_bytes()

    assert sanitize_pickled_settings(path) == 0

    assert path.read_bytes() == sanitized
    assert len(backup_files(path)) == 1


def test_missing_file_is_not_an_error(tmp_path):
    path = tmp_path / "barbaros.conf"

    assert sanitize_pickled_settings(path) == 0

    assert not path.exists()
    assert backup_files(path) == []


def test_none_path_is_not_an_error():
    assert sanitize_pickled_settings(None) is None


def test_marker_inside_an_ordinary_string_is_kept(tmp_path):
    # Only a QVariant holding a pickled object may be dropped; a user string
    # that merely mentions the wrapper class is data.
    payload = b'[main_window]\nnote="PySide::PyObjectWrapper"\n'
    path = write_config(tmp_path / "barbaros.conf", payload)

    assert sanitize_pickled_settings(path) == 0

    assert path.read_bytes() == payload
    assert backup_files(path) == []


def test_symlinked_config_is_not_followed(tmp_path, legacy_pickled_config):
    # A dotfiles-managed symlink cannot be sanitized in place: the raw file is
    # read without following links, so the sanitizer reports failure and the
    # read guard in ``common.read_setting`` keeps the app startable.
    target = write_config(tmp_path / "dotfiles" / "barbaros.conf", legacy_pickled_config)
    link = tmp_path / "barbaros.conf"
    link.symlink_to(target)

    assert sanitize_pickled_settings(link) is None

    assert target.read_bytes() == legacy_pickled_config
    assert backup_files(link) == []


def test_oversized_file_is_left_untouched(tmp_path, legacy_pickled_config):
    payload = legacy_pickled_config + b" " * MAX_SETTINGS_BYTES
    path = write_config(tmp_path / "barbaros.conf", payload)

    assert sanitize_pickled_settings(path) is None

    assert path.read_bytes() == payload
    assert backup_files(path) == []


def test_settings_file_path_matches_qt_default(qapp):
    expected = Path(QSettings(QSettings.Scope.UserScope).fileName())

    assert settings_file_path() == expected


# --- QSettings ordering contract --------------------------------------------


@rejects_legacy_pickle
def test_qsettings_rejects_unsanitized_legacy_config(tmp_path, legacy_pickled_config):
    """Documents the crash this migration fixes: the first read raises."""
    path = write_config(tmp_path / "barbaros.conf", legacy_pickled_config)
    settings = QSettings(str(path), QSettings.Format.IniFormat)

    with pytest.raises(RuntimeError):
        settings.value("main_window/target_language")


@rejects_legacy_pickle
def test_sanitized_config_is_readable_by_qsettings(tmp_path, legacy_pickled_config):
    path = write_config(tmp_path / "barbaros.conf", legacy_pickled_config)
    assert sanitize_pickled_settings(path) == 2

    settings = QSettings(str(path), QSettings.Format.IniFormat)

    assert settings.value("main_window/target_language") == "ru"
    assert settings.value("main_window/target_language_list") == "ar,de,en,ru"
    assert isinstance(settings.value("main_window/geometry"), QByteArray)
    assert settings.value("main_window/model") is None
    assert set(settings.allKeys()) == {
        "main_window/geometry",
        "main_window/target_language",
        "main_window/target_language_list",
    }


@rejects_legacy_pickle
def test_read_setting_recovers_a_neighbour_value(tmp_path, legacy_pickled_config):
    """The rejected value is in the section, not in the key: the retry recovers it."""
    path = write_config(tmp_path / "barbaros.conf", legacy_pickled_config)
    settings = QSettings(str(path), QSettings.Format.IniFormat)

    assert read_setting(settings, "main_window/target_language", "fallback") == "ru"
    assert read_setting(settings, "main_window/target_language_list") == "ar,de,en,ru"


@rejects_legacy_pickle
def test_read_setting_returns_default_for_the_rejected_key(
    tmp_path, legacy_pickled_config
):
    path = write_config(tmp_path / "barbaros.conf", legacy_pickled_config)
    settings = QSettings(str(path), QSettings.Format.IniFormat)

    # The first read raises (section parse), the retry finds no value for this
    # very key: the caller's default wins instead of None.
    assert read_setting(settings, "main_window/model", "fallback") == "fallback"


# --- tolerant readers --------------------------------------------------------


class _BrokenSettings:
    """QSettings stand-in whose every read raises the PySide6 6.12 error."""

    def __init__(self):
        self.calls = 0

    def value(self, key, default=None):
        self.calls += 1
        raise RuntimeError("Failed to deserialize Python object from QDataStream.")


class _FlakySettings:
    """Raises once (the section parse), then behaves like a normal QSettings."""

    def __init__(self):
        self.calls = 0

    def value(self, key, default=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Failed to deserialize Python object from QDataStream.")
        return "recovered"


class _TextSettings:
    def __init__(self, values: dict[str, str]):
        self.values = values

    def value(self, key, default=None):
        return self.values.get(key, default)


def test_read_setting_retries_once_and_recovers():
    settings = _FlakySettings()

    assert read_setting(settings, "main_window/target_language", "default") == "recovered"
    assert settings.calls == 2


def test_read_setting_returns_default_when_qt_raises_twice():
    settings = _BrokenSettings()

    assert read_setting(settings, "main_window/model", "default") == "default"
    assert settings.calls == 2


def test_settings_proxy_does_not_raise_on_broken_settings():
    proxy = SettingsProxy(_BrokenSettings(), "main_window")

    assert proxy.value("model", "default") == "default"
    assert proxy.valueFromJson("model", {"fallback": True}) == {"fallback": True}


def test_value_from_json_returns_default_for_invalid_json():
    proxy = SettingsProxy(_TextSettings({"main_window/model": "{not json"}), "main_window")

    assert proxy.valueFromJson("model", ("fallback",)) == ("fallback",)


def test_value_from_json_returns_default_for_deeply_nested_json():
    """RecursionError is a RuntimeError subclass and must not abort startup."""
    nested = "[" * 5000 + "]" * 5000
    proxy = SettingsProxy(_TextSettings({"main_window/model": nested}), "main_window")

    assert proxy.valueFromJson("model", ("fallback",)) == ("fallback",)
