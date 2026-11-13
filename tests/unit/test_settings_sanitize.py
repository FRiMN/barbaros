"""Unit tests for the BAR-01/BAR-28 settings-file preparation.

The ``legacy_pickled_config`` fixture (tests/conftest.py) recreates what
PySide6 writes for ``QSettings.setValue`` with a Python object.  Under
PySide6 >= 6.12 Qt refuses to deserialize such values, so the tests that rely
on that refusal are skipped on older versions.

The BAR-28 tests ("fail-closed preparation") patch the version gate to make the
*safe* runtime behave like PySide6 6.11; the real 6.11 runtime behaviour is
exercised by the opt-in Flatpak test (``tests/system/test_flatpak_pyside.py``).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QByteArray, QSettings

from barbaros import settings_sanitize
from barbaros.common import SettingsProxy, read_setting
from barbaros.settings_sanitize import (
    MAX_SETTINGS_BYTES,
    PICKLE_MARKER,
    MemoryBackedSettings,
    prepare_settings_file,
    pyside_rejects_pickled_values,
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


# --- BAR-28: fail-closed preparation ----------------------------------------


@pytest.fixture
def unpickles_pyside(monkeypatch):
    """Make the running (safe) PySide6 behave like the 6.11 Flatpak runtime."""
    monkeypatch.setattr(
        settings_sanitize, "pyside_rejects_pickled_values", lambda: False
    )


def test_version_gate_matches_the_running_pyside():
    assert pyside_rejects_pickled_values() is QT_REJECTS_PICKLED_OBJECTS


def test_unparsable_version_is_treated_as_unsafe(monkeypatch):
    monkeypatch.setattr(settings_sanitize, "pyside_version", "unknown-build")

    assert pyside_rejects_pickled_values() is False


@rejects_legacy_pickle
def test_clean_config_prepares_without_quarantine(tmp_path):
    path = write_config(tmp_path / "barbaros.conf", b"[main_window]\ntarget_language=ru\n")

    prepared = prepare_settings_file(path)

    assert prepared.removed == 0
    assert prepared.quarantined is None
    assert prepared.memory_backed is False
    assert path.read_bytes() == b"[main_window]\ntarget_language=ru\n"


@rejects_legacy_pickle
def test_missing_config_prepares_without_quarantine(tmp_path):
    prepared = prepare_settings_file(tmp_path / "barbaros.conf")

    assert prepared.removed == 0
    assert prepared.quarantined is None
    assert prepared.memory_backed is False


def test_unknown_path_uses_memory_when_pyside_unpickles(unpickles_pyside):
    prepared = prepare_settings_file(None)

    assert prepared.memory_backed is True
    assert prepared.quarantined is None


@rejects_legacy_pickle
def test_oversized_config_is_left_alone_on_safe_pyside(tmp_path, legacy_pickled_config):
    """On PySide6 >= 6.12 an unclean file is harmless: keep the preferences."""
    payload = legacy_pickled_config + b" " * MAX_SETTINGS_BYTES
    path = write_config(tmp_path / "barbaros.conf", payload)

    prepared = prepare_settings_file(path)

    assert prepared.removed is None
    assert prepared.quarantined is None
    assert prepared.memory_backed is False
    assert path.read_bytes() == payload


def test_any_existing_config_is_not_read_when_pyside_unpickles(
    tmp_path, legacy_pickled_config, unpickles_pyside
):
    """On an old runtime the file is not read at all: it is moved aside.

    Even a *clean* file is quarantined: Qt unescapes the INI text before it
    decides that a value is an ``@Variant``, so "the scan found nothing" cannot
    prove a file harmless (BAR-28).
    """
    payload = legacy_pickled_config + b" " * MAX_SETTINGS_BYTES
    path = write_config(tmp_path / "barbaros.conf", payload)

    prepared = prepare_settings_file(path)

    assert prepared.removed is None
    assert prepared.memory_backed is True
    quarantine = prepared.quarantined
    assert quarantine is not None
    assert quarantine.parent == path.parent
    assert ".unsafe-" in quarantine.name
    # The whole file moved: QSettings never sees it, the payload is kept as a
    # quarantine backup for the user.
    assert not os.path.lexists(path)
    assert quarantine.read_bytes() == payload
    assert stat.S_IMODE(quarantine.stat().st_mode) == 0o600


def test_clean_config_is_quarantined_when_pyside_unpickles(
    tmp_path, unpickles_pyside
):
    path = write_config(tmp_path / "barbaros.conf", b"[main_window]\ntarget_language=ru\n")

    prepared = prepare_settings_file(path)

    assert prepared.memory_backed is True
    assert prepared.quarantined is not None
    assert not os.path.lexists(path)
    assert prepared.quarantined.read_bytes() == b"[main_window]\ntarget_language=ru\n"


def test_symlinked_config_is_quarantined_without_touching_target(
    tmp_path, legacy_pickled_config, unpickles_pyside
):
    target = write_config(
        tmp_path / "dotfiles" / "barbaros.conf", legacy_pickled_config
    )
    target_mode = stat.S_IMODE(target.stat().st_mode)
    link = tmp_path / "barbaros.conf"
    link.symlink_to(target)

    prepared = prepare_settings_file(link)

    assert prepared.memory_backed is True
    quarantine = prepared.quarantined
    assert quarantine is not None
    # The directory entry moved, the target is untouched (and its mode is not
    # narrowed through the link).
    assert not os.path.lexists(link)
    assert stat.S_ISLNK(quarantine.lstat().st_mode)
    assert target.read_bytes() == legacy_pickled_config
    assert stat.S_IMODE(target.stat().st_mode) == target_mode


def test_read_only_directory_uses_memory_without_a_backup(
    tmp_path, legacy_pickled_config, unpickles_pyside
):
    """A file that cannot be moved aside is simply never read: the app starts."""
    config_dir = tmp_path / "config"
    path = write_config(config_dir / "barbaros.conf", legacy_pickled_config)
    config_dir.chmod(0o500)
    try:
        prepared = prepare_settings_file(path)
    finally:
        config_dir.chmod(0o700)

    assert prepared.removed is None
    assert prepared.quarantined is None
    assert prepared.memory_backed is True
    # The application never wrote or removed the file.
    assert path.read_bytes() == legacy_pickled_config


# --- BAR-28: escapes are not a security boundary on old PySide ---------------


def escaped_variant_config(legacy_pickled_config: bytes) -> bytes:
    """The scanner-invisible form Qt still parses as a pickled variant.

    Qt unescapes ``\\xHH`` before it checks the value, so escaping the ``@`` of
    ``@Variant(`` (or one byte of the marker) hides the value from a raw-byte
    scan while QSettings on PySide6 < 6.12 still unpickles it.
    """
    return legacy_pickled_config.replace(b"=@Variant(", b"=\\x40Variant(").replace(
        b"PySide::PyObjectWrapper", b"PySide::PyObject\\x57rapper"
    )


def test_escaped_variant_is_invisible_to_the_raw_byte_scan(tmp_path, legacy_pickled_config):
    path = write_config(tmp_path / "barbaros.conf", escaped_variant_config(legacy_pickled_config))

    assert sanitize_pickled_settings(path) == 0

    data = path.read_bytes()
    assert b"\\x40Variant(" in data
    assert b"Object\\x57rapper" in data


def test_escaped_variant_is_not_trusted_on_old_pyside(
    tmp_path, legacy_pickled_config, unpickles_pyside
):
    path = write_config(tmp_path / "barbaros.conf", escaped_variant_config(legacy_pickled_config))

    prepared = prepare_settings_file(path)

    # The scanner says "clean"; the old runtime must still not read the file.
    assert prepared.memory_backed is True
    assert prepared.quarantined is not None
    assert not os.path.lexists(path)
    data = prepared.quarantined.read_bytes()
    assert b"\\x40Variant(" in data


@rejects_legacy_pickle
def test_escaped_variant_is_parsed_by_new_pyside(tmp_path, legacy_pickled_config):
    """Proves the parser differential exists: Qt unescapes and then unpickles.

    On >= 6.12 Qt refuses (RuntimeError) - but it *tries*, so the same file on
    6.11.x would execute the payload if the app ever read it.
    """
    path = write_config(tmp_path / "barbaros.conf", escaped_variant_config(legacy_pickled_config))
    settings = QSettings(str(path), QSettings.Format.IniFormat)

    with pytest.raises(RuntimeError):
        settings.value("main_window/model")


# --- BAR-28: quoted pickled variants ----------------------------------------


def make_quoted_pickled_config(path: Path) -> bytes:
    """A real QSettings INI value with a *quoted* ``@Variant`` pickle.

    QSettings quotes a value that contains a comma, and a comma is an ordinary
    pickle byte (``0x2c``), so some payload lengths produce the quoted form.
    The loop finds such a payload on the running PySide instead of hard-coding
    its pickle layout.
    """

    class Payload:
        def __init__(self, marker):
            self.marker = marker

        def __reduce__(self):
            # Only takes effect if something unpickles this file: never does.
            return (open, (self.marker, "w"))

    for length in range(1, 200):
        settings = QSettings(str(path), QSettings.Format.IniFormat)
        settings.clear()
        settings.setValue("main_window/model", Payload("/nonexistent/" + "x" * length))
        settings.sync()
        data = path.read_bytes()
        if b'="@Variant(' in data:
            return data
    pytest.skip("the running PySide pickle layout does not quote the value")


def test_quoted_pickled_variant_is_removed(tmp_path):
    path = tmp_path / "barbaros.conf"
    payload = make_quoted_pickled_config(path)
    assert PICKLE_MARKER in payload

    assert sanitize_pickled_settings(path) == 1

    data = path.read_bytes()
    assert PICKLE_MARKER not in data
    assert b"model=" not in data
    assert backup_files(path)[0].read_bytes() == payload


def test_quoted_pickled_variant_is_not_read_on_unsafe_pyside(
    tmp_path, unpickles_pyside
):
    """A quoted pickle is not trusted on an old runtime either: no read at all."""
    path = tmp_path / "barbaros.conf"
    make_quoted_pickled_config(path)

    prepared = prepare_settings_file(path)

    assert prepared.memory_backed is True
    assert prepared.quarantined is not None
    assert not os.path.lexists(path)


def test_quoted_string_starting_with_variant_prefix_is_kept(tmp_path):
    payload = b'[main_window]\nnote="@Variant(ordinary text)"\n'
    path = write_config(tmp_path / "barbaros.conf", payload)

    assert sanitize_pickled_settings(path) == 0

    assert path.read_bytes() == payload


# --- in-memory settings (used instead of any file on PySide6 < 6.12) --------


def test_memory_settings_behaves_like_the_qsettings_subset_used_by_the_app():
    settings = MemoryBackedSettings()

    assert settings.value("missing", "default") == "default"
    settings.setValue("main_window/model", '{"provider": "ollama"}')
    assert settings.value("main_window/model") == '{"provider": "ollama"}'
    assert settings.contains("main_window/model")
    settings.remove("main_window/model")
    assert not settings.contains("main_window/model")
    settings.sync()  # no-op, must not raise
    assert settings.fileName() == ""


def test_memory_settings_supports_the_settings_proxy():
    settings = MemoryBackedSettings()
    proxy = SettingsProxy(settings, "main_window")

    proxy.setValue("target_language", "ru")
    proxy.setValueAsJson("model", {"provider": "ollama", "model": "llama3"})

    assert proxy.value("target_language") == "ru"
    assert proxy.valueFromJson("model") == {"provider": "ollama", "model": "llama3"}
    assert proxy.childKeys() == ["model", "target_language"]
    assert settings.allKeys() == ["main_window/model", "main_window/target_language"]
    assert settings.childGroups() == ["main_window"]
    # beginGroup/endGroup nesting restores the previous (here empty) group.
    settings.beginGroup("a")
    settings.beginGroup("b")
    settings.endGroup()
    settings.endGroup()
    assert settings.allKeys() == ["main_window/model", "main_window/target_language"]


def test_memory_settings_matches_qsettings_group_semantics(tmp_path):
    """The in-memory stand-in keeps the QSettings grouping contract."""
    disk = QSettings(str(tmp_path / "qt.ini"), QSettings.Format.IniFormat)
    memory = MemoryBackedSettings()
    for settings in (disk, memory):
        settings.setValue("z_key", 1)
        settings.setValue("main_window/model", "m")
        settings.setValue("main_window/target_language", "ru")
        settings.setValue("alpha/beta/c", 2)

    for group in (None, "main_window", "alpha/beta"):
        if group is not None:
            disk.beginGroup(group)
            memory.beginGroup(group)
        assert memory.allKeys() == disk.allKeys()
        assert memory.childKeys() == disk.childKeys()
        assert memory.childGroups() == disk.childGroups()
        if group is not None:
            disk.endGroup()
            memory.endGroup()


def test_memory_settings_returns_qbytearray_as_stored():
    settings = MemoryBackedSettings()
    geometry = QByteArray(b"geometry-bytes")

    settings.setValue("main_window/geometry", geometry)

    assert settings.value("main_window/geometry") is geometry
