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
* The on-disk format (version, allowlist, limits, serialization and
  deserialization) lives in :class:`ModelCacheDocument`; the store owns the
  path, file mechanics (:mod:`barbaros.atomic_file`), the write lock, the
  fail-safe boundaries and the logging context.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

from barbaros.atomic_file import read_regular_file_limited, write_bytes_atomic

logger = logging.getLogger(__name__)

_LOG_STRING_LIMIT = 64
_MODELS_FILENAME = "models.json"

#: QSettings key (application scope) that may override the default cache file.
SETTINGS_KEY = "model_cache_path"


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


def _default_cache_path() -> Path | None:
    """Resolve the default cache file; ``None`` when disabled or on failure."""
    from PySide6.QtCore import QStandardPaths

    try:
        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
    except Exception as exc:  # Fail-safe boundary: construction never raises.
        logger.warning(
            "Model cache: path resolution failed (%s)", exc.__class__.__name__
        )
        return None

    if not base:
        return None

    return Path(base) / _MODELS_FILENAME


class DocumentTooLarge(ValueError):
    """The encoded document exceeds the byte limit requested by the store."""

    def __init__(self, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(f"{size} > {limit} bytes")


class InvalidDocument(ValueError):
    """The bytes are not a valid cache document.

    ``reason`` is a stable machine-readable code; ``cause`` preserves the
    underlying decode/parse exception for the ``"json"`` case, so the store can
    keep logging the original exception class name.
    """

    def __init__(self, reason: str, *, cause: BaseException | None = None) -> None:
        self.reason = reason
        self.cause = cause
        super().__init__(reason)


class ModelCacheDocument:
    """Validated representation and codec of the on-disk model cache document.

    Owns the schema policy (version, allowlist, limits, sanitization) and both
    directions of the file format. It knows nothing about paths, files, locks
    or fallback logging: the store maps its typed errors to the usual WARNINGs.
    Instances are sanitized snapshots; the input mapping is never referenced.
    """

    VERSION = 1
    MAX_PROVIDERS = 1000
    MAX_MODELS_PER_PROVIDER = 10_000
    MAX_PROVIDER_NAME_LEN = 256
    MAX_MODEL_ID_LEN = 1024
    MAX_OWNED_BY_LEN = 256
    ALLOWED_MODEL_KEYS = ("id", "created", "object", "owned_by")

    def __init__(self, models: Mapping[str, Sequence[Mapping[str, object]]]) -> None:
        self._models = self._sanitize(models)

    @property
    def models(self) -> dict[str, list[dict]]:
        """Sanitized ``{provider: [model entry, ...]}`` snapshot."""
        return self._models

    @classmethod
    def from_bytes(cls, raw: bytes) -> ModelCacheDocument:
        """Decode and validate a cache document stored as UTF-8 JSON bytes.

        Raises:
            InvalidDocument: with reason ``"json"`` (decode/parse failure),
                ``"top_level"``, ``"version"`` or ``"models"``.
        """
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError) as exc:
            raise InvalidDocument("json", cause=exc) from exc

        if not isinstance(document, dict):
            raise InvalidDocument("top_level")

        version = document.get("version")
        if type(version) is not int or version != cls.VERSION:
            raise InvalidDocument("version")

        models = document.get("models")
        if not isinstance(models, dict):
            raise InvalidDocument("models")

        return cls(models)

    def to_bytes(self, max_bytes: int) -> bytes:
        """Encode as compact UTF-8 JSON; raise ``DocumentTooLarge`` over the limit."""
        payload = json.dumps(
            {"version": self.VERSION, "models": self._models},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")

        if len(payload) > max_bytes:
            raise DocumentTooLarge(size=len(payload), limit=max_bytes)

        return payload

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


_INVALID_DOCUMENT_MESSAGES = {
    "top_level": "Model cache: top-level JSON is not an object, ignored: %r",
    "version": "Model cache: unsupported schema version, ignored: %r",
    "models": "Model cache: invalid 'models' section, ignored: %r",
}


class ModelCacheStore:
    """Fail-safe JSON store for the per-provider model cache.

    The store owns the path, file mechanics (via :mod:`barbaros.atomic_file`),
    the write lock, the fail-safe boundaries and the logging context; the
    on-disk format itself is :class:`ModelCacheDocument`. ``load`` and ``save``
    never raise; every failure is logged and reported as an empty cache /
    ``False``.

    ``path`` is resolved once in the constructor (an explicitly passed path wins
    and never touches Qt) and is not modified afterwards; ``None`` means the
    store is disabled because the default location is unavailable.
    """

    MAX_FILE_BYTES = 4 * 1024 * 1024

    path: Path | None

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_cache_path()
        self._write_lock = threading.Lock()

    def load(self) -> dict[str, list[dict]]:
        """Return the sanitized cache; ``{}`` for any missing/invalid file."""
        path = self.path
        if path is None:
            return {}

        raw = self._read_payload(path)
        if raw is None:
            return {}

        return self._parse_payload(path, raw)

    def save(self, models: Mapping[str, Sequence[Mapping[str, object]]]) -> bool:
        """Atomically persist the sanitized snapshot; ``False`` on any failure."""
        path = self.path
        if path is None:
            return False

        payload = self._serialize_payload(path, models)
        if payload is None:
            return False

        return self._write_payload(path, payload)

    def _read_payload(self, path: Path) -> bytes | None:
        """Read the cache bytes; ``None`` when the file is absent or unusable."""
        try:
            return read_regular_file_limited(
                path,
                self.MAX_FILE_BYTES,
                logger=logger,
                label="Model cache",
            )
        except Exception as exc:  # Defensive: the helper is fail-safe by contract.
            logger.warning(
                "Model cache: read failed for %r (%s)", path, exc.__class__.__name__
            )
            return None

    def _parse_payload(self, path: Path, raw: bytes) -> dict[str, list[dict]]:
        """Deserialize via the document; map its errors to the usual WARNINGs."""
        try:
            return ModelCacheDocument.from_bytes(raw).models

        except InvalidDocument as exc:
            if exc.reason == "json":
                logger.warning(
                    "Model cache: load failed for %r (%s)",
                    path,
                    (exc.cause or exc).__class__.__name__,
                )
            else:
                message = _INVALID_DOCUMENT_MESSAGES.get(exc.reason)
                if message is None:
                    logger.warning(
                        "Model cache: load failed for %r (%s)",
                        path,
                        exc.__class__.__name__,
                    )
                else:
                    logger.warning(message, path)
            return {}

        except Exception as exc:  # Fail-safe boundary: errors never propagate.
            logger.warning(
                "Model cache: load failed for %r (%s)", path, exc.__class__.__name__
            )
            return {}

    def _serialize_payload(
        self,
        path: Path,
        models: Mapping[str, Sequence[Mapping[str, object]]],
    ) -> bytes | None:
        """Serialize via the document; ``None`` with a WARNING on failure."""
        try:
            document = ModelCacheDocument(models)
            return document.to_bytes(max_bytes=self.MAX_FILE_BYTES)

        except DocumentTooLarge as exc:
            logger.warning(
                "Model cache: payload too large (%d > %d bytes), not saved: %r",
                exc.size,
                exc.limit,
                path,
            )
            return None

        except Exception as exc:  # Fail-safe boundary: errors never propagate.
            logger.warning(
                "Model cache: serialization failed for %r (%s)",
                path,
                exc.__class__.__name__,
            )
            return None

    def _write_payload(self, path: Path, payload: bytes) -> bool:
        """Atomically write a serialized payload.

        Serialization runs outside the lock: snapshot ordering is guaranteed by
        ModelManager's RLock, this lock only serializes file replacements.
        """
        try:
            with self._write_lock:
                return write_bytes_atomic(
                    path,
                    payload,
                    logger=logger,
                    label="Model cache",
                )
        except Exception as exc:  # Defensive: the helper is fail-safe by contract.
            logger.warning(
                "Model cache: save failed for %r (%s)", path, exc.__class__.__name__
            )
            return False
