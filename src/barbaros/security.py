"""API-key storage for provider secrets (BAR-11).

One facade, one active store.  The application currently has a single store,
:class:`KeyringSecretStore` (the system keyring); the unencrypted-file store is a
follow-up issue, and the facade exists so that adding it does not touch the
call sites.  There is deliberately **no fallback** between stores and no
in-memory session store: a key is either persisted in the active store or the
operation fails loudly, because a ``Save`` that silently keeps the key only
until exit breaks the button's contract.

Typed results instead of exceptions
-----------------------------------
The keyring is an I/O boundary and its failures are normal states, not
programming errors: no backend/Secret Service, a locked collection, a dead
D-Bus session, a corrupt entry.  Every operation therefore returns a typed
status and never raises:

* :class:`SecretStatus` -- ``FOUND``, ``MISSING``, ``LOCKED``, ``UNAVAILABLE``,
  ``CORRUPT``.  ``LOCKED`` is retryable and is *not* "no key".
* :class:`WriteStatus` -- ``PERSISTED`` or ``ERROR``.
* :class:`Availability` -- a startup probe (``READY``/``UNAVAILABLE``).

Only callers that need the actual value raise :class:`SecretStorageError`, whose
message is user-facing, localized by the widget layer, and never contains the
secret (see :meth:`ApiKeyManager.value`).

What the boundary catches
-------------------------
``keyring.errors.KeyringError`` is *not* sufficient: when the ``SecretService``
backend is selected and the D-Bus daemon disappears, ``secretstorage.dbus_init``
raises ``FileNotFoundError``; a backend may also raise ``KeyringLocked`` (a
``KeyringError``) or fail to decode the stored bytes (``UnicodeDecodeError``).
The store maps every exception of this boundary to a status, logging only the
provider name and the exception class name -- never ``str(exc)``, which for a
decode error can quote the stored bytes.

Backend vetting
---------------
Every operation refuses a keyring backend that would silently store secrets in
plaintext or drop them: ``keyring.backends.fail`` (no backend at all),
``keyring.backends.null`` (reads return nothing, writes are discarded), any
``keyrings.alt`` backend (including a chainer that wraps one) and a subclass of
one of those.  Installing ``keyrings.alt`` makes ``keyring`` auto-select its
plaintext backend without asking the user, so the refusal is what keeps "no
plaintext without consent" true -- it must gate the write path too, not only
the banner.  The check inspects backend classes (MRO and a chainer's wrapped
backends); it never reads a secret and never triggers an unlock prompt.  A retry
(``refresh=True``) re-runs keyring's cached backend detection, so a login race
can be recovered without restarting the app.

``availability()`` is a *class-level capability* probe, not a liveness check:
if the selected backend dies after the probe (e.g. the D-Bus session goes away),
``availability()`` keeps reporting ``READY`` while reads return ``UNAVAILABLE``
(and the banner appears after the next refresh/restart).  Operations always
re-check the backends they are about to use.

Logging hygiene
---------------
Only provider names (rendered with ``repr`` and truncated, so a name cannot
forge a log record), typed statuses and exception class names reach the log.
Secrets never appear in log records, error messages or dialogs (BAR-17).

Non-goals
---------
Key lifecycle (revocation on provider removal, rotation, "delete saved key") is
BAR-02 (issue #8) and stays out of this module.  This module also cannot stop a
same-uid process from reading the keyring; the audit's threat model already
treats a same-uid process as trusted (BAR-10).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

import keyring
import keyring.backend
import keyring.core
from keyring.backends import fail as fail_backend
from keyring.errors import KeyringLocked, PasswordDeleteError

logger = logging.getLogger(__name__)

#: Keyring service name.  Kept unchanged from the pre-refactoring code so that
#: keys saved by older versions stay readable (no migration step).
SERVICE_NAME = "barbaros:providers_api_keys"

#: Provider names come from the config file and the UI; a name longer than this
#: is not a provider name.  The limit keeps a hostile config from producing
#: unbounded keyring lookups.
MAX_PROVIDER_NAME_LEN = 256

#: API keys are short opaque tokens.  A value over this limit is treated as a
#: corrupt entry instead of being rendered or sent to a provider.
MAX_SECRET_LEN = 16 * 1024

_LOG_STRING_LIMIT = 64

_NULL_BACKEND_MODULE = "keyring.backends.null"
#: The chainer multiplexes backends.  It is matched by module name on purpose:
#: importing ``keyring.backends.chainer`` would register ``ChainerBackend`` in
#: keyring's global backend registry and could change keyring's own selection
#: (it wins with priority 10 when more than one positive-priority backend
#: exists).  The import must stay side-effect free (BAR-11).
_CHAINER_BACKEND_MODULE = "keyring.backends.chainer"
_REFUSED_BACKEND_MODULES = ("keyrings.alt",)


class SecretStatus(Enum):
    """Outcome of reading a secret.

    ``CORRUPT`` is reserved for a value the store cannot represent as a usable
    string; the keyring store never returns it for a *missing* entry.
    """

    FOUND = "found"
    MISSING = "missing"
    LOCKED = "locked"
    UNAVAILABLE = "unavailable"
    CORRUPT = "corrupt"


class WriteStatus(Enum):
    """Outcome of storing or deleting a secret."""

    PERSISTED = "persisted"
    ERROR = "error"


class Availability(Enum):
    """Outcome of the non-prompting startup probe."""

    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SecretRead:
    """Result of a read.

    ``value`` is set only for ``FOUND``; ``reason`` is a machine-readable code
    (or an exception class name) used for logs and the UI, never a secret.
    """

    status: SecretStatus
    value: str | None = None
    reason: str | None = None


@runtime_checkable
class SecretStore(Protocol):
    """Storage backend port.

    Implementations never raise: every failure is a typed status.  They own the
    backend-specific error mapping; the facade owns the app-wide validation
    (provider-name and secret limits) and stays mode-independent.
    """

    def availability(self, *, refresh: bool = False) -> Availability:
        """Whether the store can be used, without reading a secret."""

    def read(self, provider_name: str) -> SecretRead:
        """Read the secret for ``provider_name``."""

    def write(self, provider_name: str, value: str) -> WriteStatus:
        """Persist ``value`` for ``provider_name``."""

    def delete(self, provider_name: str) -> WriteStatus:
        """Remove the secret for ``provider_name`` (idempotent)."""


def _safe(value: object) -> str:
    """Render an external string for a log line: ``repr`` and truncated (BAR-17)."""
    return repr(str(value)[:_LOG_STRING_LIMIT])


def _reset_backend_detection() -> None:
    """Re-run keyring's backend detection after a failed startup probe.

    ``keyring.backend.get_all_keyring`` is cached for the life of the process
    (``jaraco.functools.once``); without resetting it a login race where the
    Secret Service was not up yet keeps ``fail.Keyring`` selected until restart.

    The two steps are guarded separately on purpose: ``reset()`` raises
    ``KeyError`` when the detection cache was never populated (for example after
    an explicit ``keyring.set_keyring(...)`` before any detection), and that is
    not a failure of the re-detection that follows.
    """
    try:
        keyring.backend.get_all_keyring.reset()
    except KeyError:
        # Nothing cached yet: there is nothing to drop, re-detection still runs.
        pass
    except Exception as exc:  # Fail-safe boundary: a probe never raises.
        logger.warning(
            "Secret storage: keyring detection reset failed (%s)",
            exc.__class__.__name__,
        )

    try:
        keyring.core.init_backend()
    except Exception as exc:  # Fail-safe boundary: a probe never raises.
        logger.warning(
            "Secret storage: keyring re-detection failed (%s)", exc.__class__.__name__
        )


def _module_refusal(module: str) -> str | None:
    """Why a backend class from ``module`` must not be used, or ``None``."""
    if module == _NULL_BACKEND_MODULE or module.startswith(_NULL_BACKEND_MODULE + "."):
        return "null-backend"

    for refused in _REFUSED_BACKEND_MODULES:
        if module == refused or module.startswith(refused + "."):
            return "plaintext-alternative"

    return None


def _class_refusal(backend: object) -> str | None:
    """Why a backend *class* must not be used, or ``None``.

    The whole MRO is inspected, so a subclass defined outside a refused package
    is still caught through its refused base class.
    """
    if isinstance(backend, fail_backend.Keyring):
        return "no-backend"

    for klass in type(backend).__mro__:
        reason = _module_refusal(klass.__module__ or "")
        if reason is not None:
            return reason

    return None


def _is_chainer_backend(backend: object) -> bool:
    """Whether ``backend`` is keyring's chainer, without importing it.

    Importing ``keyring.backends.chainer`` registers the class in keyring's
    global backend registry, which can change keyring's own backend selection;
    the module must not do that (BAR-11).  The whole MRO is checked, so a
    subclass defined outside ``keyring.backends.chainer`` (which inherits the
    chainer's write-through behaviour) is still recognised.
    """
    return any(
        klass.__module__ == _CHAINER_BACKEND_MODULE for klass in type(backend).__mro__
    )


def _backend_refusal(backend: object) -> str | None:
    """Why a selected backend must not be used, or ``None`` when it is fine."""
    refusal = _class_refusal(backend)
    if refusal is not None:
        return refusal

    # A chainer multiplexes other backends (including a keyrings.alt one): if any
    # wrapped backend would be refused, using the chainer is not safe either.
    # An empty chainer would silently report success and store nothing, so it is
    # refused like the null backend (reachable only by explicit configuration:
    # auto-detection never selects it with fewer than two viable backends).
    if _is_chainer_backend(backend):
        wrapped = list(backend.backends)
        if not wrapped:
            return "chained-empty"

        for inner in wrapped:
            reason = _class_refusal(inner)
            if reason is not None:
                return f"chained-{reason}"

    return None


def _read_failure(provider_name: str, exc: BaseException) -> SecretRead:
    """Map a read exception to a status, logging only the class name."""
    if isinstance(exc, KeyringLocked):
        status = SecretStatus.LOCKED
    elif isinstance(exc, UnicodeDecodeError):
        status = SecretStatus.CORRUPT
    else:
        status = SecretStatus.UNAVAILABLE

    logger.warning(
        "Secret storage: cannot read the key for %s (%s -> %s)",
        _safe(provider_name),
        exc.__class__.__name__,
        status.value,
    )
    return SecretRead(status, reason=exc.__class__.__name__)


class KeyringSecretStore:
    """System-keyring backend (:class:`SecretStore`)."""

    def availability(self, *, refresh: bool = False) -> Availability:
        """Probe the selected backend without reading a secret."""
        if refresh:
            _reset_backend_detection()

        _, refusal = self._usable_backend()
        if refusal is not None:
            return Availability.UNAVAILABLE

        return Availability.READY

    def _usable_backend(self) -> tuple[object | None, str | None]:
        """Select the backend for one operation.

        Returns ``(backend, None)`` when the backend may be used, or
        ``(None, reason)`` (already logged) when it must not.  Availability and
        every operation share this check, so a refused backend can neither be
        reported ready nor silently store or drop a secret.  The returned
        instance is the one the operation uses, so a concurrent backend swap
        cannot route a vetted call to another backend.
        """
        try:
            backend = keyring.get_keyring()
        except Exception as exc:  # Fail-safe boundary: never raises.
            logger.warning(
                "Secret storage: backend selection failed (%s)", exc.__class__.__name__
            )
            return None, "selection-failed"

        try:
            refusal = _backend_refusal(backend)
        except Exception as exc:  # Fail-safe boundary: never raises.
            # Inspection can evaluate other backends (a chainer's members, their
            # priorities).  A broken third-party backend must degrade to "not
            # usable", not raise into the GUI like the defect this fixes.
            logger.warning(
                "Secret storage: backend inspection failed (%s)",
                exc.__class__.__name__,
            )
            return None, "inspection-failed"

        if refusal is not None:
            logger.warning(
                "Secret storage: keyring backend refused (reason=%s, backend=%s)",
                refusal,
                type(backend).__name__,
            )
            return None, refusal

        return backend, None

    def read(self, provider_name: str) -> SecretRead:
        backend, refusal = self._usable_backend()
        if backend is None:
            return SecretRead(SecretStatus.UNAVAILABLE, reason=refusal)

        try:
            value = backend.get_password(SERVICE_NAME, provider_name)
        except Exception as exc:  # I/O boundary: every failure is a status.
            return _read_failure(provider_name, exc)

        return self._validate_value(provider_name, value)

    @staticmethod
    def _validate_value(provider_name: str, value: object) -> SecretRead:
        """Turn a backend return value into FOUND/MISSING/CORRUPT."""
        if value is None:
            return SecretRead(SecretStatus.MISSING)

        if not isinstance(value, str):
            logger.warning(
                "Secret storage: key for %s is not text (%s)",
                _safe(provider_name),
                type(value).__name__,
            )
            return SecretRead(SecretStatus.CORRUPT, reason="non-text")

        if not value:
            # An empty entry cannot be a usable API key; the write path never
            # stores one, so this is a corrupt/foreign entry.
            logger.warning("Secret storage: key for %s is empty", _safe(provider_name))
            return SecretRead(SecretStatus.CORRUPT, reason="empty")

        if len(value) > MAX_SECRET_LEN:
            logger.warning(
                "Secret storage: key for %s is too large (%d > %d chars)",
                _safe(provider_name),
                len(value),
                MAX_SECRET_LEN,
            )
            return SecretRead(SecretStatus.CORRUPT, reason="too-large")

        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            # A lone surrogate would fail later in the HTTP layer: fail closed.
            logger.warning(
                "Secret storage: key for %s cannot be encoded as UTF-8",
                _safe(provider_name),
            )
            return SecretRead(SecretStatus.CORRUPT, reason="unencodable")

        return SecretRead(SecretStatus.FOUND, value=value)

    def write(self, provider_name: str, value: str) -> WriteStatus:
        backend, refusal = self._usable_backend()
        if backend is None:
            return WriteStatus.ERROR

        try:
            backend.set_password(SERVICE_NAME, provider_name, value)
        except Exception as exc:  # I/O boundary: every failure is a status.
            logger.warning(
                "Secret storage: cannot save the key for %s (%s)",
                _safe(provider_name),
                exc.__class__.__name__,
            )
            return WriteStatus.ERROR

        return WriteStatus.PERSISTED

    def delete(self, provider_name: str) -> WriteStatus:
        backend, refusal = self._usable_backend()
        if backend is None:
            return WriteStatus.ERROR

        try:
            backend.delete_password(SERVICE_NAME, provider_name)
        except PasswordDeleteError:
            # Nothing to delete: deletion is idempotent, not a failure.
            return WriteStatus.PERSISTED
        except Exception as exc:  # I/O boundary: every failure is a status.
            logger.warning(
                "Secret storage: cannot delete the key for %s (%s)",
                _safe(provider_name),
                exc.__class__.__name__,
            )
            return WriteStatus.ERROR

        return WriteStatus.PERSISTED


def _valid_provider_name(provider_name: object) -> bool:
    return (
        isinstance(provider_name, str)
        and bool(provider_name)
        and len(provider_name) <= MAX_PROVIDER_NAME_LEN
    )


def _valid_secret(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > MAX_SECRET_LEN:
        return False

    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        # A lone surrogate cannot be sent to a provider; refuse it at the door.
        return False

    return True


class SecretStorage:
    """App-facing facade over one :class:`SecretStore`.

    Validates the app-wide input rules (provider-name and secret limits) and
    delegates the rest, so switching the store never changes call-site
    behaviour.  Invalid input is a programming error but is reported as a
    status with a WARNING, never raised into the GUI.
    """

    def __init__(self, store: SecretStore) -> None:
        self._store = store

    @property
    def store(self) -> SecretStore:
        return self._store

    def availability(self, *, refresh: bool = False) -> Availability:
        return self._store.availability(refresh=refresh)

    def get(self, provider_name: str) -> SecretRead:
        if not _valid_provider_name(provider_name):
            logger.warning(
                "Secret storage: invalid provider name for a key lookup (%s)",
                type(provider_name).__name__,
            )
            return SecretRead(SecretStatus.MISSING, reason="invalid-name")

        return self._store.read(provider_name)

    def set(self, provider_name: str, key: str) -> WriteStatus:
        if not _valid_provider_name(provider_name) or not _valid_secret(key):
            logger.warning(
                "Secret storage: refusing to save a key (provider name or secret "
                "does not fit the limits)"
            )
            return WriteStatus.ERROR

        return self._store.write(provider_name, key)

    def delete(self, provider_name: str) -> WriteStatus:
        if not _valid_provider_name(provider_name):
            logger.warning(
                "Secret storage: invalid provider name for a key deletion (%s)",
                type(provider_name).__name__,
            )
            return WriteStatus.ERROR

        return self._store.delete(provider_name)


_USER_MESSAGES = {
    SecretStatus.LOCKED: (
        "The system keyring is locked. Unlock it and try again."
    ),
    SecretStatus.UNAVAILABLE: (
        "API key storage is unavailable: the system keyring cannot be reached. "
        "The operation was cancelled and nothing was sent."
    ),
    SecretStatus.CORRUPT: (
        "The saved API key cannot be read (the keyring entry is corrupt). "
        "Re-enter the key to replace it."
    ),
}


class SecretStorageError(RuntimeError):
    """An operation needed an API key and the active store could not provide it.

    The message is meant for the user, contains no secret and is stable; the
    typed status lets the UI add its own translated wording when it wants to.
    """

    def __init__(self, status: SecretStatus) -> None:
        self.status = status
        super().__init__(_USER_MESSAGES.get(status, "API key storage error."))


class ApiKeyManager:
    """Per-provider binding to the app-selected :class:`SecretStorage`.

    ``ProviderMeta`` creates one with the default keyring store so a standalone
    provider object still works; ``ModelManager.add`` binds the same manager to
    the storage the composition root selected.  There is no per-provider cache,
    so a retry after the store becomes available is just another call.
    """

    def __init__(
        self, provider_name: str, storage: SecretStorage | None = None
    ) -> None:
        self.provider_name = provider_name
        self._storage = storage

    @property
    def storage(self) -> SecretStorage:
        if self._storage is None:
            self._storage = SecretStorage(KeyringSecretStore())
        return self._storage

    def bind(self, storage: SecretStorage) -> None:
        """Use the composition root's storage from now on."""
        self._storage = storage

    def get(self) -> SecretRead:
        return self.storage.get(self.provider_name)

    def set(self, key: str) -> WriteStatus:
        return self.storage.set(self.provider_name, key)

    def delete(self) -> WriteStatus:
        return self.storage.delete(self.provider_name)

    def value(self) -> str | None:
        """The stored key, ``None`` when none is stored.

        Raises :class:`SecretStorageError` when the store cannot provide the
        key (locked, unavailable, corrupt): callers must abort instead of
        treating the failure as an empty key.
        """
        result = self.get()
        if result.status is SecretStatus.FOUND:
            return result.value
        if result.status is SecretStatus.MISSING:
            return None

        raise SecretStorageError(result.status)
