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
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths

from .atomic_file import read_regular_file_limited, write_bytes_atomic

logger = logging.getLogger(__name__)

# The payload of a pickled Python object as written by PySide; both markers are
# needed to tell such a value from an ordinary string that mentions the class.
PICKLE_MARKER = b"PySide::PyObjectWrapper"
VARIANT_PREFIX = b"@Variant("

# QSettings files are small; a larger one is not ours to rewrite (BAR-14).
MAX_SETTINGS_BYTES = 1024 * 1024


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
    non-printable bytes, so a legacy value always occupies a single line that
    starts with ``@Variant(``.  Other lines are copied verbatim.
    """
    lines = data.splitlines(keepends=True)
    kept: list[bytes] = []
    removed = 0

    for line in lines:
        key, separator, value = line.partition(b"=")
        if (
            separator
            and value.lstrip().startswith(VARIANT_PREFIX)
            and PICKLE_MARKER in value
        ):
            removed += 1
            continue
        kept.append(line)

    return b"".join(kept), removed


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
