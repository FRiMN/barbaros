"""JSON-file cache for provider model lists (see docs/model-cache-storage.md).

Invariants:

* The file is untrusted input. It can be corrupt, oversized, a symlink, or be
  replaced by another process at any moment. ``load``/``save`` never raise and
  never crash the application.
* The cache is regenerable. Losing it only means the model list is empty until
  the user reloads it; a bad file is ignored but never deleted, so it stays
  inspectable (and the next successful ``save`` replaces it atomically).
* No secrets. Only the model fields from the allowlist are stored; API keys
  and ``api_base`` are never written here.
* No Qt/domain dependencies at import time: the store works with plain
  ``dict[str, list[dict]]`` and knows nothing about ``Model``, ``QSettings``,
  keyring, or ``any_llm``. ``QStandardPaths`` is imported lazily only when the
  default path is resolved.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
import tempfile
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

_LOG_STRING_LIMIT = 64
_MODELS_FILENAME = "models.json"
_READ_CHUNK_BYTES = 64 * 1024

#: QSettings key (application scope) that may override the default cache file.
SETTINGS_KEY = "model_cache_path"

# O_NOFOLLOW/O_NONBLOCK/O_CLOEXEC are POSIX-only; getattr keeps the module
# importable elsewhere, the same way O_BINARY is Windows-only.
_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_BINARY", 0)
)


def _log_value(value: object) -> str:
    """Render an external string for a log line: escaped (``%r``) and short.

    Untrusted provider names may contain newlines/control characters; logging
    them through ``repr`` and truncating avoids log injection (BAR-17).
    """
    return repr(str(value)[:_LOG_STRING_LIMIT])


def cache_path_from_config(value: object) -> Path | None:
    """Resolve the optional ``model_cache_path`` override from the config.

    The value is user configuration, i.e. untrusted input.  Only a non-empty
    absolute path is accepted; a leading ``~`` is expanded (a shell-like
    convenience, not a search path).  Anything else is logged and treated as
    "not configured", so the store keeps the default AppDataLocation instead
    of writing to the process working directory or some other implicit place.

    Returns:
        The explicit cache file path, or ``None`` to auto-resolve the default.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        logger.warning(
            "Model cache: ignoring non-string '%s' setting (%s)",
            SETTINGS_KEY,
            type(value).__name__,
        )
        return None

    raw = value.strip()
    if not raw:
        return None

    try:
        path = Path(raw).expanduser()
    except RuntimeError:
        # pathlib raises when a ``~user`` form cannot be resolved (unknown user,
        # missing HOME).  The config is untrusted input: fall back, don't crash.
        logger.warning(
            "Model cache: cannot expand '%s' setting, using the default "
            "location: %s",
            SETTINGS_KEY,
            _log_value(raw),
        )
        return None
    if not path.is_absolute():
        logger.warning(
            "Model cache: '%s' must be an absolute path, using the default "
            "location: %s",
            SETTINGS_KEY,
            _log_value(raw),
        )
        return None
    return path


def _read_regular_file(path: Path, limit: int) -> bytes | None:
    """Read at most ``limit`` bytes from a regular file, never following links.

    Returns ``None`` (after logging) when the file cannot be opened, is not a
    regular file (symlink/FIFO/device/directory), or exceeds ``limit``.
    """
    try:
        fd = os.open(path, _READ_FLAGS)
    except FileNotFoundError:
        # Normal state on first run or after the cache was pruned: not a fault.
        logger.debug("Model cache: no cache file at %r", path)
        return None
    except OSError as exc:
        logger.warning("Model cache: cannot open %r (%s)", path, exc.__class__.__name__)
        return None

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            logger.warning("Model cache: not a regular file, ignored: %r", path)
            return None
        if info.st_size > limit:
            logger.warning(
                "Model cache: file too large (%d > %d bytes), ignored: %r",
                info.st_size,
                limit,
                path,
            )
            return None
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(fd, min(remaining, _READ_CHUNK_BYTES))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    except OSError as exc:
        logger.warning(
            "Model cache: read failed for %r (%s)", path, exc.__class__.__name__
        )
        return None
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)

    if len(data) > limit:
        # The file grew between fstat() and read(); drop it instead of parsing.
        logger.warning(
            "Model cache: file too large (%d > %d bytes), ignored: %r",
            len(data),
            limit,
            path,
        )
        return None
    return data


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write to model cache temp file")
        view = view[written:]


def _chmod_temp_file(fd: int) -> None:
    fchmod = getattr(os, "fchmod", None)
    if fchmod is None:  # Windows: mkstemp already creates a private file.
        return
    try:
        fchmod(fd, 0o600)
    except OSError as exc:
        logger.debug(
            "Model cache: could not set temp file mode (%s)", exc.__class__.__name__
        )


def _tighten_directory(directory: Path) -> None:
    try:
        os.chmod(directory, 0o700)
    except OSError as exc:
        # Best effort: saving the cache must not fail because of permissions
        # that are already narrower (or because another user owns the dir).
        logger.debug(
            "Model cache: could not set directory mode on %r (%s)",
            directory,
            exc.__class__.__name__,
        )


def _fsync_directory(directory: Path) -> None:
    try:
        dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError as exc:
        logger.debug(
            "Model cache: could not open directory for fsync (%s)",
            exc.__class__.__name__,
        )
        return
    try:
        os.fsync(dir_fd)
    except OSError as exc:
        logger.debug("Model cache: directory fsync failed (%s)", exc.__class__.__name__)
    finally:
        with contextlib.suppress(OSError):
            os.close(dir_fd)


def _ensure_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    _tighten_directory(directory)


def _atomic_write(path: Path, payload: bytes) -> None:
    """Write ``payload`` to ``path`` atomically, keeping the old file on error."""
    parent = path.parent
    fd, temp_name = tempfile.mkstemp(prefix=".models-", suffix=".tmp", dir=parent)
    temp_path = Path(temp_name)
    try:
        _chmod_temp_file(fd)
        try:
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_path)
        raise

    _fsync_directory(parent)


class ModelCacheStore:
    """Fail-safe JSON store for the per-provider model cache.

    The store knows only plain ``dict[str, list[dict]]``: no Qt, no keyring, no
    LLM SDK. ``load`` and ``save`` never raise; every failure is logged and
    reported as an empty cache / ``False``.
    """

    VERSION = 1
    MAX_FILE_BYTES = 4 * 1024 * 1024
    MAX_PROVIDERS = 1000
    MAX_MODELS_PER_PROVIDER = 10_000
    MAX_PROVIDER_NAME_LEN = 256
    MAX_MODEL_ID_LEN = 1024
    MAX_OWNED_BY_LEN = 256
    ALLOWED_MODEL_KEYS = ("id", "created", "object", "owned_by")

    def __init__(self, path: Path | None = None) -> None:
        self._explicit_path = Path(path) if path is not None else None
        self._resolved: Path | None = None
        self._disabled = False
        self._write_lock = threading.Lock()

    @property
    def path(self) -> Path | None:
        """Cache file path, or ``None`` when the store is disabled.

        An explicitly injected path wins and never touches Qt. Otherwise the
        location is resolved lazily (after ``setApplicationName``) to
        ``QStandardPaths.AppDataLocation/models.json``; an empty location
        disables the store instead of writing to the current directory.
        """
        if self._explicit_path is not None:
            return self._explicit_path
        if self._resolved is None and not self._disabled:
            from PySide6.QtCore import QStandardPaths

            base = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
            if base:
                self._resolved = Path(base) / _MODELS_FILENAME
            else:
                self._disabled = True
        return self._resolved

    def load(self) -> dict[str, list[dict]]:
        """Return the sanitized cache; ``{}`` for any missing/invalid file."""
        try:
            path = self.path
        except Exception as exc:  # Fail-safe boundary: errors never propagate.
            logger.warning(
                "Model cache: path resolution failed (%s)", exc.__class__.__name__
            )
            return {}
        if path is None:
            return {}

        try:
            raw = _read_regular_file(path, self.MAX_FILE_BYTES)
        except Exception as exc:  # Fail-safe boundary: read errors never propagate.
            logger.warning(
                "Model cache: read failed for %r (%s)", path, exc.__class__.__name__
            )
            return {}
        if raw is None:
            return {}

        try:
            document = json.loads(raw.decode("utf-8"))
            if not isinstance(document, dict):
                logger.warning(
                    "Model cache: top-level JSON is not an object, ignored: %r", path
                )
                return {}
            if (
                type(document.get("version")) is not int
                or document.get("version") != self.VERSION
            ):
                logger.warning(
                    "Model cache: unsupported schema version, ignored: %r", path
                )
                return {}
            models = document.get("models")
            if not isinstance(models, dict):
                logger.warning(
                    "Model cache: invalid 'models' section, ignored: %r", path
                )
                return {}
            return self._sanitize(models)
        except Exception as exc:  # Fail-safe boundary: errors never propagate.
            logger.warning(
                "Model cache: load failed for %r (%s)", path, exc.__class__.__name__
            )
            return {}

    def save(self, models: Mapping[str, Sequence[Mapping[str, object]]]) -> bool:
        """Atomically persist the sanitized snapshot; ``False`` on any failure."""
        try:
            path = self.path
        except Exception as exc:  # Fail-safe boundary: errors never propagate.
            logger.warning(
                "Model cache: path resolution failed (%s)", exc.__class__.__name__
            )
            return False
        if path is None:
            return False

        try:
            document = {"version": self.VERSION, "models": self._sanitize(models)}
            payload = json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except Exception as exc:  # Fail-safe boundary: errors never propagate.
            logger.warning(
                "Model cache: serialization failed for %r (%s)",
                path,
                exc.__class__.__name__,
            )
            return False

        if len(payload) > self.MAX_FILE_BYTES:
            logger.warning(
                "Model cache: payload too large (%d > %d bytes), not saved: %r",
                len(payload),
                self.MAX_FILE_BYTES,
                path,
            )
            return False

        try:
            _ensure_directory(path.parent)
            with self._write_lock:
                _atomic_write(path, payload)
        except Exception as exc:  # Fail-safe boundary: errors never propagate.
            logger.warning(
                "Model cache: save failed for %r (%s)", path, exc.__class__.__name__
            )
            return False
        return True

    def _sanitize(self, models: object) -> dict[str, list[dict]]:
        """Apply the shared allowlist/limits; identical on load and save."""
        if not isinstance(models, Mapping):
            return {}

        sanitized: dict[str, list[dict]] = {}
        skipped_models = 0
        for name, entries in models.items():
            if len(sanitized) >= self.MAX_PROVIDERS:
                break
            if (
                not isinstance(name, str)
                or not 0 < len(name) <= self.MAX_PROVIDER_NAME_LEN
            ):
                logger.debug(
                    "Model cache: skipped provider with invalid name %s",
                    _log_value(name),
                )
                continue
            if not isinstance(entries, list):
                logger.debug(
                    "Model cache: skipped provider %s with non-list models",
                    _log_value(name),
                )
                continue
            cleaned: list[dict] = []
            for entry in entries:
                if len(cleaned) >= self.MAX_MODELS_PER_PROVIDER:
                    break
                model = self._sanitize_model(entry)
                if model is None:
                    skipped_models += 1
                else:
                    cleaned.append(model)
            if cleaned:
                sanitized[name] = cleaned

        if skipped_models:
            logger.debug(
                "Model cache: skipped %d invalid model entries", skipped_models
            )
        return sanitized

    def _sanitize_model(self, entry: object) -> dict | None:
        if not isinstance(entry, dict):
            return None
        model_id = entry.get("id")
        if (
            not isinstance(model_id, str)
            or not 0 < len(model_id) <= self.MAX_MODEL_ID_LEN
        ):
            return None
        created = entry.get("created")
        if type(created) is not int:
            return None
        if entry.get("object") != "model":
            return None
        owned_by = entry.get("owned_by")
        if not isinstance(owned_by, str) or len(owned_by) > self.MAX_OWNED_BY_LEN:
            return None
        return {key: entry[key] for key in self.ALLOWED_MODEL_KEYS}
