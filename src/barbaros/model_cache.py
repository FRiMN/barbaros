"""JSON-file cache for provider model lists (see docs/model-cache-storage.md).

Invariants:

* The file is untrusted input. It can be corrupt, oversized, a symlink, or be
  replaced by another process at any moment. ``load``/``save`` never raise and
  never crash the application.
* The cache is regenerable. Losing it only means the model list is empty until
  the user reloads it; a bad or foreign file is ignored but never deleted and
  never replaced (``save`` writes only to a missing file or to an existing
  model-cache document, BAR-19), so it stays inspectable and recoverable.
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
import os
import stat
import threading
from collections.abc import Mapping
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

    def __init__(self, models: Mapping[str, list[Mapping[str, object]]]) -> None:
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
        document = cls._decode_envelope(raw)

        version = document.get("version")
        if type(version) is not int or version != cls.VERSION:
            raise InvalidDocument("version")

        models = document.get("models")
        if not isinstance(models, dict):
            raise InvalidDocument("models")

        return cls(models)

    @classmethod
    def is_cache_document(cls, raw: bytes) -> bool:
        """Whether ``raw`` uses the model-cache envelope (any schema version).

        This is the write-side identity check (BAR-19): ``save`` may replace a
        file only when it uses the cache envelope. Any integer ``version`` is
        accepted, so a cache written by another version (an upgrade or a
        downgrade) is still recognized and replaced; the cache is regenerable,
        so that is normal recovery rather than data loss. Extra top-level keys
        are tolerated. The model entries are not validated: the question here
        is "is this our file", not "can it be loaded" (loading stays
        version-strict in :meth:`from_bytes`).

        This is an identity heuristic, not proof: a foreign JSON object with
        the same envelope would be accepted, and a cache file above the store's
        ``MAX_FILE_BYTES`` read cap cannot be verified, so it is refused. The
        envelope (JSON object, integer ``version``, object ``models``) is
        therefore a compatibility constraint for future schema versions: a
        future format must keep it, otherwise the write guard would refuse to
        replace a real cache file.
        """
        try:
            document = cls._decode_envelope(raw)
        except InvalidDocument:
            return False

        return type(document.get("version")) is int and isinstance(
            document.get("models"), dict
        )

    @classmethod
    def _decode_envelope(cls, raw: bytes) -> dict:
        """Decode UTF-8 JSON and require an object at the top level."""
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError) as exc:
            raise InvalidDocument("json", cause=exc) from exc

        if not isinstance(document, dict):
            raise InvalidDocument("top_level")

        return document

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
    store is disabled because the default location is unavailable. Only the
    app-resolved default directory is tightened to ``0700``; a caller-supplied
    path (the ``model_cache_path`` override) may point into an existing shared
    directory whose mode must not change. The cache file itself is always
    written with ``0600``.
    """

    MAX_FILE_BYTES = 4 * 1024 * 1024

    path: Path | None

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_cache_path()
        self._write_lock = threading.Lock()
        # Only the app-resolved default location is ours: an explicitly passed
        # path (model_cache_path) can point into a shared directory, where
        # changing the mode would be a destructive surprise. The cache file
        # itself is still written with 0600.
        self._tighten_directory = path is None
        # Identity (device, inode, size, mtime_ns, ctime_ns) of the file this
        # store wrote last; while it matches, the target is our own unchanged
        # cache and its content does not need to be re-read on every save.
        self._verified_target: tuple[int, int, int, int, int] | None = None
        self._refusals_warned: set[tuple[str, str]] = set()

    def load(self) -> dict[str, list[dict]]:
        """Return the sanitized cache; ``{}`` for any missing/invalid file."""
        path = self.path
        if path is None:
            return {}

        raw = self._read_payload(path)
        if raw is None:
            return {}

        return self._parse_payload(path, raw)

    def save(self, models: Mapping[str, list[Mapping[str, object]]]) -> bool:
        """Persist the sanitized snapshot; ``False`` on any failure or refusal.

        An existing target is replaced only when it is a model-cache file; a
        missing target is created (BAR-19, :meth:`_may_replace`).
        """
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
        models: Mapping[str, list[Mapping[str, object]]],
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

    def _may_replace(self, path: Path) -> bool:
        """Whether ``path`` may be replaced: missing, or an existing cache file.

        ``model_cache_path`` is untrusted config, so ``os.replace`` must not be
        allowed to destroy an arbitrary user-writable file (BAR-19). A missing
        target is the normal first save; an existing one must use the
        model-cache envelope of any schema version. Everything else (symlink,
        FIFO, device, directory, unreadable, oversized or foreign file) is left
        byte-for-byte intact and reported as a WARNING: a false refusal costs
        one cache reload, a false accept would destroy user data.

        After a successful write, the target's identity (device, inode, size,
        mtime and ctime) is recorded. While it still matches, the file is the
        one this store wrote and has not changed, so it is not re-read and
        re-parsed on every save. An external modification or replacement
        changes at least one field and triggers the full check again.

        The check and the ``os.replace`` are not one atomic operation - a
        same-uid process can still swap the target in between. Such a process
        is outside the audit threat model (it can already write the file); this
        guard targets accidental, synced or foreign files, not an active
        attacker racing the application.
        """
        try:
            target = os.lstat(path)
        except FileNotFoundError:
            return True
        except OSError as exc:  # Fail-safe boundary: never propagate.
            return self._refuse(
                "inspect",
                path,
                "Model cache: cannot inspect the target, not saved: %r (%s)",
                exc.__class__.__name__,
            )

        if self._stat_signature(target) == self._verified_target:
            return True

        if not stat.S_ISREG(target.st_mode):
            return self._refuse(
                "not-regular",
                path,
                "Model cache: target is not a regular file, not saved: %r",
            )

        raw = read_regular_file_limited(
            path,
            self.MAX_FILE_BYTES,
            logger=logger,
            label="Model cache",
        )
        if raw is None:
            return self._refuse(
                "unreadable",
                path,
                "Model cache: target cannot be verified as a model cache, "
                "not saved: %r",
            )

        if not ModelCacheDocument.is_cache_document(raw):
            return self._refuse(
                "not-cache",
                path,
                "Model cache: target is not a model cache, not saved: %r "
                "(move it aside to let Barbaros recreate the cache)",
            )

        return True

    def _refuse(self, reason: str, path: Path, message: str, *args: object) -> bool:
        """Log a write refusal once per ``(reason, path)``; return ``False``.

        A misconfigured path would otherwise repeat the same WARNING on every
        save (one per provider on a bulk reload). The first occurrence is a
        WARNING, repeats are DEBUG; a later successful write clears the record.
        """
        key = (reason, os.fspath(path))
        if key in self._refusals_warned:
            logger.debug(message, path, *args)
        else:
            self._refusals_warned.add(key)
            logger.warning(message, path, *args)
        return False

    @staticmethod
    def _stat_signature(info: os.stat_result) -> tuple[int, int, int, int, int]:
        """Identity of a filesystem entry for the write-guard memo."""
        return (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    @staticmethod
    def _signature_of(path: Path) -> tuple[int, int, int, int, int] | None:
        """Current memo signature of ``path``; ``None`` when it is unreadable."""
        try:
            return ModelCacheStore._stat_signature(os.lstat(path))
        except OSError:
            return None

    def _write_payload(self, path: Path, payload: bytes) -> bool:
        """Atomically write a serialized payload after the write-side check.

        Serialization runs outside the lock: snapshot ordering is guaranteed by
        ModelManager's RLock, this lock only serializes file replacements.
        """
        try:
            with self._write_lock:
                if not self._may_replace(path):
                    return False
                written = write_bytes_atomic(
                    path,
                    payload,
                    logger=logger,
                    label="Model cache",
                    tighten_directory=self._tighten_directory,
                )
                if written:
                    self._refusals_warned.clear()
                    self._verified_target = self._signature_of(path)
                return written
        except Exception as exc:  # Defensive: the helper is fail-safe by contract.
            logger.warning(
                "Model cache: save failed for %r (%s)", path, exc.__class__.__name__
            )
            return False
