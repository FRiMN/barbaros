"""Drop legacy pickled Python objects from the QSettings INI file (BAR-01).

PySide6 serializes a Python object passed to ``QSettings.setValue()`` as
``@Variant(... PySide::PyObjectWrapper ...)`` with pickle.  Older versions
unpickled such a value on read (CWE-502); PySide6 6.12 rejects it instead: the
first ``QSettings.value()`` that parses a section holding such a value raises
``RuntimeError``, which aborted startup.  Model selections are stored as JSON
now, so the legacy entries are only migration debris and are removed here.

The file must be sanitized *before* the first ``QSettings`` object for it is
constructed: ``QSettings`` snapshots the raw INI text in its constructor, so
rewriting the file afterwards has no effect on that instance.  The file name of
``QSettings.Scope.UserScope``/``IniFormat`` is resolved the way Qt resolves it
on Unix (``$XDG_CONFIG_HOME/<organization>/<application>.conf``); the
application keeps a plain ``QSettings(Scope.UserScope)`` so a wrong guess
cannot silence a real settings read.

Mechanics follow ``barbaros.atomic_file``: the raw file is read without
following symlinks and with a byte cap, the original is kept as a timestamped
backup next to it, and the replacement is atomic and durable.  A failed
sanitization (read-only config directory, symlinked file, ...) is logged and
never fatal: the settings read path degrades to defaults
(``common.read_setting``), trading a lost preference for a startable
application (AGENTS.md #14).

That fail-open trade is only safe on PySide6 >= 6.12, which refuses to
deserialize the value.  Older PySide6 (the Flatpak release shipped 6.11.x from
its base app for a while) executes the pickle while parsing the section, and Qt
unescapes/unquotes the INI text first, so no raw-byte scan can prove such a file
harmless (BAR-28).  ``prepare_settings_file`` therefore does not read the
on-disk file at all on an old runtime: it moves an existing file aside as a
``*.unsafe-*`` quarantine backup and the application uses an in-memory settings
object for the session (``MemoryBackedSettings``).  A same-uid process can
replace any file the application is able to read, so a throwaway *file* would
only narrow the race; without a file there is nothing to read and the
application always starts (losing the preferences is the accepted trade).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QCoreApplication, QStandardPaths

from .atomic_file import read_regular_file_limited, write_bytes_atomic

logger = logging.getLogger(__name__)

# The payload of a pickled Python object as written by PySide; both markers are
# needed to tell such a value from an ordinary string that mentions the class.
PICKLE_MARKER = b"PySide::PyObjectWrapper"
VARIANT_PREFIX = b"@Variant("

# QSettings files are small; a larger one is not ours to rewrite (BAR-14).
MAX_SETTINGS_BYTES = 1024 * 1024

# PySide6 6.12 rejects a pickled ``QSettings`` value instead of executing it;
# older versions unpickle it while parsing the section (BAR-01, BAR-28).
PYSIDE_SAFE_VERSION = (6, 12)
_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)")


def pyside_rejects_pickled_values() -> bool:
    """Whether the running PySide6 refuses pickled ``QSettings`` values.

    ``True`` on PySide6 >= 6.12, where reading such a value raises instead of
    deserializing it.  A version string that cannot be parsed counts as unsafe:
    an unknown runtime must not be trusted with a file that may hold a pickle
    (fail-closed, BAR-28).
    """
    match = _VERSION_PATTERN.match(pyside_version)
    if match is None:
        logger.warning(
            "Settings: unrecognized PySide6 version %r, assuming pickled values "
            "are unsafe",
            pyside_version,
        )
        return False
    return (int(match.group(1)), int(match.group(2))) >= PYSIDE_SAFE_VERSION


@dataclass(frozen=True)
class SettingsFilePreparation:
    """How ``App`` must back its settings after the pre-start sanitization.

    ``removed`` is the number of pickled values dropped from the effective
    settings, or ``None`` when the file could not be cleaned.
    ``quarantined`` is where an existing file was moved aside (best-effort
    backup; empty on a missing file or when the move was impossible).
    ``memory_backed`` says the caller must use ``MemoryBackedSettings`` instead
    of any ``QSettings`` file: on a PySide6 that still unpickles, no on-disk
    settings are read at all, because a same-uid process can replace any file
    the application can read (BAR-28).
    """

    removed: int | None = 0
    quarantined: Path | None = None
    memory_backed: bool = False


def prepare_settings_file(path: Path | None) -> SettingsFilePreparation:
    """Sanitize the settings file and decide how to open ``QSettings``.

    On PySide6 >= 6.12 a pickled value is rejected instead of deserialized, so
    an unclean file is harmless: it is cleaned for the legacy-data migration and
    ``common.read_setting`` covers whatever the scan missed.

    On PySide6 < 6.12 no on-disk settings are read.  Qt unescapes and unquotes
    the INI text before it decides that a value is an ``@Variant``, so the raw
    bytes can hide the prefix or a marker byte behind an escape
    (``\\x40Variant(``, ``PyObject\\x57rapper``): a raw-byte scan cannot prove a
    file safe.  A same-uid process can replace any file the application is able
    to read, so even a throwaway file would only narrow the race - the caller
    uses ``MemoryBackedSettings`` and an existing settings file is moved aside
    as a best-effort quarantine backup.  The preferences of the old session are
    not carried over, which is the accepted trade for never handing
    attacker-writable bytes to a runtime that executes them.  Never raises.
    """
    if pyside_rejects_pickled_values():
        return SettingsFilePreparation(removed=sanitize_pickled_settings(path))

    logger.warning(
        "Settings: PySide6 %s unpickles QSettings values, so no on-disk "
        "settings are read; they are kept in memory for this session (BAR-28)",
        pyside_version,
    )

    quarantined = None
    if path is not None:
        # Best effort: the backup is for the user, not a security boundary (the
        # application does not read the file at all).
        quarantined = _quarantine_settings_file(path)

    return SettingsFilePreparation(
        removed=None, quarantined=quarantined, memory_backed=True
    )


def _quarantine_settings_file(path: Path) -> Path | None:
    """Move the settings file aside as a backup; return its new path, if moved.

    The application never reads the file on the runtime that calls this, so the
    move is a best-effort backup for the user, not a security step.  ``None``
    means nothing was moved: a missing file, a read-only directory, or an entry
    ``QSettings`` could not read anyway (directory, FIFO, ...).  The move acts on
    the directory entry, so a symlink is moved without touching its target.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None  # nothing to move
    except OSError as exc:
        logger.warning(
            "Settings: cannot inspect %r for quarantine (%s)",
            path,
            exc.__class__.__name__,
        )
        return None

    if not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
        logger.warning(
            "Settings: %r is neither a regular file nor a symlink, "
            "not quarantining it",
            path,
        )
        return None

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    try:
        fd, name = tempfile.mkstemp(
            prefix=f"{path.name}.unsafe-{timestamp}-", dir=path.parent
        )
        os.close(fd)
    except OSError as exc:
        logger.warning(
            "Settings: cannot reserve a quarantine name next to %r (%s)",
            path,
            exc.__class__.__name__,
        )
        return None

    destination = Path(name)
    try:
        os.replace(path, destination)
    except FileNotFoundError:
        _remove_quietly(destination)
        return None
    except OSError as exc:
        logger.warning(
            "Settings: cannot quarantine %r (%s)", path, exc.__class__.__name__
        )
        _remove_quietly(destination)
        return None

    _restrict_mode(destination)
    logger.warning(
        "Settings: moved the settings file %r aside as %r (this PySide6 does "
        "not read it, BAR-28)",
        path,
        destination,
    )
    return destination


class MemoryBackedSettings:
    """In-process stand-in for the ``QSettings`` subset the application uses.

    Used instead of reading any settings file on PySide6 < 6.12 (BAR-28): a
    same-uid process can replace any file the application is able to read, so
    pointing ``QSettings`` at a throwaway location would only widen the race.
    With no file at all there is nothing to unpickle and the application always
    starts; the price is that preferences are not persisted for the session.

    The call shape matches ``QSettings`` for the operations used by
    ``common.SettingsProxy`` and the UI: ``value``/``setValue``/``remove``/
    ``contains``, group handling, ``allKeys``/``childKeys``/``childGroups`` and
    a no-op ``sync``.  Values are returned exactly as stored (``str``,
    ``QByteArray``, ...), like ``QSettings`` does for the types the application
    writes; nothing touches the disk.
    """

    def __init__(self) -> None:
        self._values: dict[str, object] = {}
        self._group_prefix = ""

    def _key(self, key: str) -> str:
        return f"{self._group_prefix}{key}"

    def value(self, key: str, default=None):
        return self._values.get(self._key(key), default)

    def setValue(self, key: str, value) -> None:
        self._values[self._key(key)] = value

    def remove(self, key: str) -> None:
        self._values.pop(self._key(key), None)

    def contains(self, key: str) -> bool:
        return self._key(key) in self._values

    def beginGroup(self, prefix: str) -> None:
        self._group_prefix = f"{self._group_prefix}{prefix}/"

    def endGroup(self) -> None:
        parts = self._group_prefix.rstrip("/").split("/")
        self._group_prefix = f"{parts[0]}/" if len(parts) > 1 else ""

    def _keys_relative_to_group(self) -> list[str]:
        prefix = self._group_prefix
        if not prefix:
            return list(self._values)
        return [key[len(prefix):] for key in self._values if key.startswith(prefix)]

    def allKeys(self) -> list[str]:
        # QSettings: keys relative to the active group, sorted.
        return sorted(self._keys_relative_to_group())

    def childKeys(self) -> list[str]:
        return sorted(key for key in self._keys_relative_to_group() if "/" not in key)

    def childGroups(self) -> list[str]:
        return sorted(
            {
                key.split("/", 1)[0]
                for key in self._keys_relative_to_group()
                if "/" in key
            }
        )

    def sync(self) -> None:
        """No-op: memory-backed settings have nothing to flush."""

    def fileName(self) -> str:
        return ""


def _remove_quietly(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


def _restrict_mode(path: Path) -> None:
    """Best effort: keep a quarantined file as private as a backup.

    The entry may be a symlink; ``os.chmod`` would follow it and change the
    mode of the link's target - an unrelated file the application must not
    touch - so only a regular file is adjusted.
    """
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return
        os.chmod(path, 0o600)
    except OSError as exc:
        logger.debug(
            "Settings: cannot set mode on quarantine %r (%s)",
            path,
            exc.__class__.__name__,
        )


def settings_file_path() -> Path | None:
    """Path of the user-scope INI file QSettings uses on this system.

    Matches Qt's Unix file naming.  Returns ``None`` when the configuration
    location is unknown or the application metadata is incomplete, which only
    means the raw file cannot be sanitized here.
    """
    config_location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.ConfigLocation
    )
    application_name = QCoreApplication.applicationName()

    if not config_location or not application_name:
        logger.warning(
            "Settings: cannot resolve the config file path "
            "(config_location=%r, application_name=%r)",
            config_location,
            application_name,
        )
        return None

    organization = (
        QCoreApplication.organizationName() or QCoreApplication.organizationDomain()
    )
    if not organization:
        # Qt substitutes this name when both organization fields are empty.
        organization = "Unknown Organization"

    return Path(config_location) / organization / f"{application_name}.conf"


def sanitize_pickled_settings(path: Path | None) -> int | None:
    """Remove ``PySide::PyObjectWrapper`` values from the INI file at ``path``.

    Never raises.  Returns the number of removed values (``0`` when the file is
    clean, the common case), or ``None`` when the file may still contain one
    (unknown path, read-only directory, symlinked file, ...).  Call this before
    constructing ``QSettings``.
    """
    if path is None:
        return None

    try:
        data = read_regular_file_limited(
            path, MAX_SETTINGS_BYTES, logger=logger, label="Settings"
        )
        if data is None:
            # A missing file is the normal first-start state.  For any other
            # reason (symlink, permissions, size) the helper has logged why and
            # the file may still hold a pickled value: report it as unknown.
            return None if path.exists() else 0

        cleaned, removed = _strip_pickled_entries(data)
        if removed == 0:
            return 0  # fast path: no legacy pickle, leave the file alone

        backup = _write_backup(path, data)
        if backup is None:
            logger.warning(
                "Settings: legacy pickled values left in %r: no backup written",
                path,
            )
            return None

        if not write_bytes_atomic(
            path, cleaned, logger=logger, label="Settings", tighten_directory=False
        ):
            logger.warning(
                "Settings: legacy pickled values left in %r, backup at %r",
                path,
                backup,
            )
            return None

        logger.info(
            "Settings: removed %d legacy pickled value(s) from %r, backup at %r",
            removed,
            path,
            backup,
        )
        return removed
    except Exception as exc:  # Fail-safe boundary: startup must not depend on it.
        logger.warning(
            "Settings: sanitizing %r failed (%s)", path, exc.__class__.__name__
        )
        return None


def _strip_pickled_entries(data: bytes) -> tuple[bytes, int]:
    """Return ``data`` without INI values holding a pickled Python object.

    QSettings writes one ``key=value`` pair per line and escapes newlines and
    non-printable bytes, so a legacy value always occupies a single line.
    Other lines are copied verbatim.
    """
    lines = data.splitlines(keepends=True)
    kept: list[bytes] = []
    removed = 0

    for line in lines:
        key, separator, value = line.partition(b"=")
        if separator and _is_pickled_variant(value):
            removed += 1
            continue
        kept.append(line)

    return b"".join(kept), removed


def _is_pickled_variant(value: bytes) -> bool:
    """Whether an INI value holds a pickled ``PySide::PyObjectWrapper``.

    QSettings may also *quote* such a value: it quotes strings containing a
    comma, and a comma is an ordinary pickle byte (``0x2c``), so the quoted
    form is not exotic - a long enough payload produces it.  Qt still parses a
    quoted ``@Variant(...)`` as a variant when reading, so an optional leading
    quote is skipped before the prefix check (BAR-28).
    """
    candidate = value.lstrip()
    if candidate.startswith(b'"'):
        candidate = candidate[1:].lstrip()
    return candidate.startswith(VARIANT_PREFIX) and PICKLE_MARKER in value


def _write_backup(path: Path, data: bytes) -> Path | None:
    """Write the original bytes next to ``path``; ``None`` on failure.

    ``tempfile.mkstemp`` creates the backup exclusively with mode ``0600``, so
    a concurrent or immediately repeated migration cannot overwrite an earlier
    backup.  The timestamp keeps the name readable; the random suffix makes it
    unique.
    """
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    try:
        fd, name = tempfile.mkstemp(
            prefix=f"{path.name}.bak-{timestamp}-", dir=path.parent
        )
    except OSError as exc:
        logger.warning(
            "Settings backup: cannot create a file for %r (%s)",
            path,
            exc.__class__.__name__,
        )
        return None

    backup = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        logger.warning(
            "Settings backup: write failed for %r (%s)",
            backup,
            exc.__class__.__name__,
        )
        with contextlib.suppress(OSError):
            backup.unlink()
        return None
    return backup
