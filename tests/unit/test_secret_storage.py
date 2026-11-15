"""Contract tests for the typed secret-storage boundary (BAR-11, issue #9).

``barbaros.security`` treats the system keyring as an I/O boundary: no backend,
a locked collection, a dead D-Bus session or a corrupt entry are normal states,
not programming errors.  Every operation therefore returns a typed status and
never raises, and a secret value never reaches a log record or an exception
message.

The fake backends are installed with ``keyring.set_keyring``; conftest's
autouse ``fake_keyring`` fixture keeps every test away from the user's real
keyring.  No real Secret Service, D-Bus or network is involved.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import textwrap
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail, null
from keyring.errors import (
    KeyringError,
    KeyringLocked,
    NoKeyringError,
    PasswordDeleteError,
)

import barbaros.security as security
from barbaros.security import (
    MAX_PROVIDER_NAME_LEN,
    MAX_SECRET_LEN,
    SERVICE_NAME,
    ApiKeyManager,
    Availability,
    KeyringSecretStore,
    SecretRead,
    SecretStatus,
    SecretStorage,
    SecretStorageError,
    SecretStore,
    WriteStatus,
)

# --- test doubles -----------------------------------------------------------


class MemoryKeyring(KeyringBackend):
    """A minimal working backend: the only one a round-trip test needs."""

    priority = 1

    def __init__(self):
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.passwords.get((service, username))

    def set_password(self, service, username, password):
        self.passwords[(service, username)] = password

    def delete_password(self, service, username):
        try:
            del self.passwords[(service, username)]
        except KeyError:
            raise PasswordDeleteError(f"no password for {username!r}") from None


class StubKeyring(KeyringBackend):
    """A backend whose operations return/raise whatever the test supplies.

    ``None`` means "operation succeeded" for write/delete and "no value" for
    read; an exception instance is raised at the boundary.
    """

    priority = 1

    def __init__(self, *, read=None, write=None, delete=None):
        self._read = read
        self._write = write
        self._delete = delete
        self.calls: list[tuple[str, str, str]] = []

    @staticmethod
    def _outcome(outcome):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def get_password(self, service, username):
        self.calls.append(("read", service, username))
        return self._outcome(self._read)

    def set_password(self, service, username, password):
        self.calls.append(("write", service, username))
        return self._outcome(self._write)

    def delete_password(self, service, username):
        self.calls.append(("delete", service, username))
        return self._outcome(self._delete)


class AltPlaintextKeyring(MemoryKeyring):
    """Presented as a ``keyrings.alt`` backend, i.e. a silent plaintext store."""


AltPlaintextKeyring.__module__ = "keyrings.alt.file"


class NullSubclass(null.Keyring):
    """A subclass defined outside the refused package is still refused."""


class ChaineredKeyringBase(MemoryKeyring):
    """A duck-typed backend class that lives in keyring's chainer module.

    The real ``keyring.backends.chainer`` must never be imported here: importing
    it registers ``ChainerBackend`` in keyring's global registry.  The subclasses
    below are defined in the test module, so recognising them requires walking
    the whole MRO (the 574ef42 fix) rather than matching the concrete module.
    """


ChaineredKeyringBase.__module__ = "keyring.backends.chainer"


class SubclassedRefusingChainer(ChaineredKeyringBase):
    """A chainer subclass wrapping a working and a refused backend."""

    backends = [MemoryKeyring(), null.Keyring()]


class SubclassedEmptyChainer(ChaineredKeyringBase):
    """A chainer subclass with nothing to chain (silently drops writes)."""

    backends: list = []


class PlaintextMemberKeyring(MemoryKeyring):
    """A chainer member from the ``keyrings.alt`` plaintext package."""


PlaintextMemberKeyring.__module__ = "keyrings.alt.file"


class SubclassedPlaintextChainer(ChaineredKeyringBase):
    """A chainer subclass whose wrapped backend stores plaintext."""

    backends = [MemoryKeyring(), PlaintextMemberKeyring()]


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class RecordingStore:
    """``SecretStore`` double that records the facade calls it receives."""

    def __init__(
        self,
        status: SecretStatus,
        *,
        value: str | None = None,
    ):
        self.status = status
        self.value = value
        self.calls: list[tuple] = []

    def availability(self, *, refresh: bool = False) -> Availability:
        self.calls.append(("availability", refresh))
        return Availability.READY

    def read(self, provider_name: str) -> SecretRead:
        self.calls.append(("read", provider_name))
        return SecretRead(self.status, value=self.value)

    def write(self, provider_name: str, value: str) -> WriteStatus:
        self.calls.append(("write", provider_name, value))
        return WriteStatus.PERSISTED

    def delete(self, provider_name: str) -> WriteStatus:
        self.calls.append(("delete", provider_name))
        return WriteStatus.PERSISTED


@pytest.fixture
def install_backend(fake_keyring):
    """Install a fake keyring backend and restore conftest's one afterwards."""

    def install(backend):
        keyring.set_keyring(backend)
        return backend

    yield install
    keyring.set_keyring(fake_keyring)


def _warnings(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno == logging.WARNING]


# --- fail backend: typed statuses, nothing raises ---------------------------


def test_fail_backend_probe_and_operations_are_typed(install_backend, caplog):
    """No backend at all is a normal state: typed results, no exception."""
    install_backend(fail.Keyring())
    store = KeyringSecretStore()

    with caplog.at_level(logging.WARNING, logger="barbaros.security"):
        assert store.availability() is Availability.UNAVAILABLE
        read = store.read("acme")
        assert read.status is SecretStatus.UNAVAILABLE
        # The refusal short-circuits before the backend is called: the reason is
        # the vetting code, not keyring's NoKeyringError from the read itself.
        assert read.reason == "no-backend"
        assert store.write("acme", "sk-fail") is WriteStatus.ERROR
        assert store.delete("acme") is WriteStatus.ERROR

    assert any("backend refused" in record.getMessage() for record in _warnings(caplog))
    assert store  # the operations above returned instead of raising


@pytest.mark.parametrize(
    ("backend_factory", "expected_reason"),
    [
        pytest.param(fail.Keyring, "no-backend", id="fail"),
        pytest.param(null.Keyring, "null-backend", id="null"),
        pytest.param(
            AltPlaintextKeyring, "plaintext-alternative", id="keyrings-alt-plaintext"
        ),
        pytest.param(NullSubclass, "null-backend", id="refused-subclass"),
        pytest.param(
            SubclassedRefusingChainer,
            "chained-null-backend",
            id="chainer-subclass-wraps-refused",
        ),
        pytest.param(
            SubclassedEmptyChainer,
            "chained-empty",
            id="chainer-subclass-empty",
        ),
        pytest.param(
            SubclassedPlaintextChainer,
            "chained-plaintext-alternative",
            id="chainer-subclass-wraps-plaintext",
        ),
    ],
)
def test_refused_backend_cannot_be_used_for_any_operation(
    backend_factory, expected_reason, install_backend
):
    """Vetting gates every operation, not only the banner: no secret lands."""
    backend = backend_factory()
    touched: list[str] = []
    for method in ("get_password", "set_password", "delete_password"):
        setattr(
            backend,
            method,
            lambda *args, _method=method, **kwargs: touched.append(_method),
        )
    install_backend(backend)
    store = KeyringSecretStore()

    assert store.availability() is Availability.UNAVAILABLE

    read = store.read("acme")
    assert read.status is SecretStatus.UNAVAILABLE
    assert read.reason == expected_reason
    assert read.value is None
    assert store.write("acme", "sk-refused") is WriteStatus.ERROR
    assert store.delete("acme") is WriteStatus.ERROR

    assert touched == []  # the refused backend was never called


def test_backend_inspection_failure_is_a_typed_unavailable(install_backend, monkeypatch, caplog):
    """A broken backend inspection degrades to unusable, never raises (OWASP nit)."""

    def broken_inspection(backend):
        raise RuntimeError("third-party backend inspection exploded")

    install_backend(MemoryKeyring())
    monkeypatch.setattr(security, "_backend_refusal", broken_inspection)
    store = KeyringSecretStore()

    with caplog.at_level(logging.WARNING, logger="barbaros.security"):
        assert store.availability() is Availability.UNAVAILABLE
        read = store.read("acme")
        assert store.write("acme", "sk-inspection") is WriteStatus.ERROR
        assert store.delete("acme") is WriteStatus.ERROR

    assert read.status is SecretStatus.UNAVAILABLE
    assert read.reason == "inspection-failed"
    assert any(
        "backend inspection failed" in record.getMessage()
        for record in _warnings(caplog)
    )


# --- working backend: persisted round-trip ----------------------------------


def test_memory_backend_round_trip_and_idempotent_delete(install_backend):
    """set -> read -> delete -> read -> delete again, exactly as the contract."""
    backend = install_backend(MemoryKeyring())
    store = KeyringSecretStore()

    assert store.availability() is Availability.READY
    assert store.read("acme") == SecretRead(SecretStatus.MISSING)

    assert store.write("acme", "sk-round-trip") is WriteStatus.PERSISTED
    # The pre-refactoring service name is kept, so old keys stay readable.
    assert backend.passwords[(SERVICE_NAME, "acme")] == "sk-round-trip"
    assert store.read("acme") == SecretRead(
        SecretStatus.FOUND, value="sk-round-trip"
    )

    assert store.delete("acme") is WriteStatus.PERSISTED
    assert store.read("acme").status is SecretStatus.MISSING
    # A missing entry on delete is success (idempotent), not an error.
    assert store.delete("acme") is WriteStatus.PERSISTED
    assert backend.passwords == {}


# --- error mapping at the keyring boundary ----------------------------------


def test_locked_backend_maps_to_locked_and_value_raises_typed_error(install_backend):
    """``KeyringLocked`` is retryable and must not be reported as "no key"."""
    secret = "sk-BAR11-LOCKED-DO-NOT-LEAK"
    install_backend(StubKeyring(read=KeyringLocked(f"cannot read {secret}")))
    store = KeyringSecretStore()

    result = store.read("acme")
    assert result.status is SecretStatus.LOCKED
    assert result.value is None

    manager = ApiKeyManager("acme", SecretStorage(store))
    with pytest.raises(SecretStorageError) as excinfo:
        manager.value()
    assert excinfo.value.status is SecretStatus.LOCKED
    assert str(excinfo.value)  # a user-facing message exists
    assert secret not in str(excinfo.value)  # ... and it never quotes the secret


def test_undecodable_value_maps_to_corrupt(install_backend):
    """A decode error is a corrupt entry, not an unavailable store."""
    decode_error = UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 2, "bad start byte")
    install_backend(StubKeyring(read=decode_error))

    result = KeyringSecretStore().read("acme")
    assert result.status is SecretStatus.CORRUPT
    assert result.value is None


def test_non_string_value_maps_to_corrupt(install_backend):
    install_backend(StubKeyring(read=b"sk-bytes"))

    result = KeyringSecretStore().read("acme")
    assert result.status is SecretStatus.CORRUPT
    assert result.value is None


def test_oversized_stored_value_maps_to_corrupt(install_backend):
    install_backend(StubKeyring(read="x" * (MAX_SECRET_LEN + 1)))

    result = KeyringSecretStore().read("acme")
    assert result.status is SecretStatus.CORRUPT
    assert result.value is None


def test_empty_stored_value_is_corrupt(install_backend):
    """The write path never stores an empty key; a foreign empty entry is corrupt."""
    install_backend(StubKeyring(read=""))

    result = KeyringSecretStore().read("acme")
    assert result.status is SecretStatus.CORRUPT
    assert result.reason == "empty"
    assert result.value is None


def test_unencodable_stored_value_is_corrupt(install_backend):
    """A lone surrogate would fail later in the HTTP layer; fail closed here."""
    install_backend(StubKeyring(read="\ud800"))

    result = KeyringSecretStore().read("acme")
    assert result.status is SecretStatus.CORRUPT
    assert result.reason == "unencodable"
    assert result.value is None


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(FileNotFoundError("D-Bus socket went away"), id="dbus-file-not-found"),
        pytest.param(OSError("connection refused"), id="os-error"),
        pytest.param(NoKeyringError("no backend"), id="no-keyring"),
        pytest.param(KeyringError("backend exploded"), id="keyring-error"),
        pytest.param(RuntimeError("unexpected"), id="arbitrary-runtime-error"),
    ],
)
def test_any_read_exception_beyond_keyring_errors_is_unavailable(
    error, install_backend, caplog
):
    """The boundary is broader than ``KeyringError`` (D-Bus raises FileNotFoundError)."""
    install_backend(StubKeyring(read=error))

    with caplog.at_level(logging.WARNING, logger="barbaros.security"):
        result = KeyringSecretStore().read("acme")

    assert result.status is SecretStatus.UNAVAILABLE
    assert result.reason == type(error).__name__
    assert _warnings(caplog)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(KeyringError("write failed"), id="keyring-error"),
        pytest.param(RuntimeError("write failed"), id="arbitrary-runtime-error"),
    ],
)
def test_write_errors_are_error_status(error, install_backend, caplog):
    install_backend(StubKeyring(write=error))

    with caplog.at_level(logging.WARNING, logger="barbaros.security"):
        assert KeyringSecretStore().write("acme", "sk-write") is WriteStatus.ERROR

    assert _warnings(caplog)


def test_delete_errors_are_error_but_missing_entry_is_success(install_backend):
    install_backend(StubKeyring(delete=RuntimeError("delete failed")))
    assert KeyringSecretStore().delete("acme") is WriteStatus.ERROR

    # PasswordDeleteError means "nothing to delete", i.e. the desired state.
    install_backend(StubKeyring(delete=PasswordDeleteError("missing")))
    assert KeyringSecretStore().delete("acme") is WriteStatus.PERSISTED


def test_secret_never_reaches_logs_or_reason(install_backend, caplog):
    """Only the exception class name is logged, never ``str(exc)``/the secret."""
    secret = "sk-BAR11-DO-NOT-LEAK-0123456789"
    failure = RuntimeError(f"operation failed for value {secret!r}")
    install_backend(StubKeyring(read=failure, write=failure))

    store = KeyringSecretStore()
    with caplog.at_level(logging.DEBUG, logger="barbaros.security"):
        result = store.read("acme")
        assert store.write("acme", secret) is WriteStatus.ERROR

    assert result.status is SecretStatus.UNAVAILABLE
    assert result.reason == "RuntimeError"
    assert secret not in caplog.text
    assert secret not in (result.reason or "")


# --- backend vetting --------------------------------------------------------


@pytest.mark.parametrize(
    "backend_factory",
    [
        pytest.param(fail.Keyring, id="fail"),
        pytest.param(null.Keyring, id="null"),
        pytest.param(AltPlaintextKeyring, id="keyrings-alt-plaintext"),
    ],
)
def test_availability_refuses_unusable_backends(
    backend_factory, install_backend, caplog
):
    """fail/null/keyrings.alt must never be probed as usable storage."""
    install_backend(backend_factory())
    store = KeyringSecretStore()

    with caplog.at_level(logging.WARNING, logger="barbaros.security"):
        assert store.availability() is Availability.UNAVAILABLE

    refused = [record for record in _warnings(caplog) if "backend refused" in record.getMessage()]
    assert len(refused) == 1


def test_availability_accepts_a_regular_backend(install_backend):
    install_backend(MemoryKeyring())

    assert KeyringSecretStore().availability() is Availability.READY


def test_availability_refresh_reruns_backend_detection(install_backend, monkeypatch):
    """``refresh=True`` retries detection; a plain probe must not."""
    install_backend(MemoryKeyring())
    reset_calls: list[bool] = []
    monkeypatch.setattr(
        security, "_reset_backend_detection", lambda: reset_calls.append(True)
    )
    store = KeyringSecretStore()

    assert store.availability(refresh=False) is Availability.READY
    assert reset_calls == []

    assert store.availability(refresh=True) is Availability.READY
    assert reset_calls == [True]


def test_backend_redetection_is_fail_safe(monkeypatch, caplog):
    """A failing re-detection is logged, never raised: a probe cannot crash."""

    def broken_init_backend():
        raise RuntimeError("detection failed")

    monkeypatch.setattr(keyring.core, "init_backend", broken_init_backend)

    with caplog.at_level(logging.WARNING, logger="barbaros.security"):
        security._reset_backend_detection()

    assert any("re-detection failed" in record.getMessage() for record in _warnings(caplog))


def test_empty_detection_cache_does_not_skip_redetection(monkeypatch, caplog):
    """``get_all_keyring.reset()`` raises KeyError when nothing was cached yet.

    That is not a detection failure: ``init_backend()`` must still run and no
    misleading warning may be logged (regression covered by 5cd5506).
    """
    init_calls: list[bool] = []

    def reset_cache():
        raise KeyError("detection cache was never populated")

    monkeypatch.setattr(keyring.backend.get_all_keyring, "reset", reset_cache)
    monkeypatch.setattr(
        keyring.core, "init_backend", lambda: init_calls.append(True)
    )

    with caplog.at_level(logging.WARNING, logger="barbaros.security"):
        security._reset_backend_detection()

    assert init_calls == [True]
    assert not [r for r in caplog.records if r.name == "barbaros.security"]


def test_availability_is_a_capability_probe_not_a_liveness_check(install_backend):
    """A backend that dies after selection is detected by the operation, not the probe."""
    backend = install_backend(MemoryKeyring())

    def service_died(*args, **kwargs):
        raise RuntimeError("Secret Service went away")

    backend.get_password = service_died
    store = KeyringSecretStore()

    assert store.availability() is Availability.READY
    result = store.read("acme")
    assert result.status is SecretStatus.UNAVAILABLE
    assert result.reason == "RuntimeError"


# --- facade validation ------------------------------------------------------


@pytest.mark.parametrize(
    "provider_name",
    [
        pytest.param("", id="empty"),
        pytest.param("x" * (MAX_PROVIDER_NAME_LEN + 1), id="oversized"),
        pytest.param(None, id="none"),
        pytest.param(42, id="int"),
        pytest.param(b"bytes", id="bytes"),
    ],
)
def test_invalid_provider_name_is_a_typed_result_with_warning(
    provider_name, install_backend, caplog
):
    backend = install_backend(StubKeyring())
    storage = SecretStorage(KeyringSecretStore())

    with caplog.at_level(logging.WARNING, logger="barbaros.security"):
        read = storage.get(provider_name)
        assert storage.set(provider_name, "sk-valid") is WriteStatus.ERROR
        assert storage.delete(provider_name) is WriteStatus.ERROR

    assert read.status is SecretStatus.MISSING
    assert read.value is None
    assert backend.calls == []  # invalid input never reaches the boundary
    assert _warnings(caplog)


def test_provider_name_at_the_limit_is_accepted(install_backend):
    name = "x" * MAX_PROVIDER_NAME_LEN
    backend = install_backend(MemoryKeyring())
    storage = SecretStorage(KeyringSecretStore())

    assert storage.get(name).status is SecretStatus.MISSING
    assert storage.set(name, "sk-at-limit") is WriteStatus.PERSISTED
    assert backend.passwords[(SERVICE_NAME, name)] == "sk-at-limit"


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("", id="empty"),
        pytest.param("x" * (MAX_SECRET_LEN + 1), id="oversized"),
        pytest.param("\ud800", id="lone-surrogate"),
        pytest.param(None, id="none"),
        pytest.param(42, id="int"),
    ],
)
def test_invalid_secret_is_error_with_warning(key, install_backend, caplog):
    backend = install_backend(StubKeyring())
    storage = SecretStorage(KeyringSecretStore())

    with caplog.at_level(logging.WARNING, logger="barbaros.security"):
        assert storage.set("acme", key) is WriteStatus.ERROR

    assert backend.calls == []
    assert _warnings(caplog)


def test_invalid_secret_is_never_logged(install_backend, caplog):
    """The validation warning must not echo the secret it refused."""
    secret = "sk-BAR11-REFUSED-DO-NOT-LEAK"
    install_backend(StubKeyring())
    storage = SecretStorage(KeyringSecretStore())

    with caplog.at_level(logging.DEBUG, logger="barbaros.security"):
        assert storage.set("acme", secret + "x" * (MAX_SECRET_LEN + 1)) is WriteStatus.ERROR

    assert secret not in caplog.text


# --- import side effects ----------------------------------------------------


def test_importing_security_does_not_touch_keyring_state():
    """Importing the module must not select a backend or run detection.

    The composition root owns backend selection; an import that triggered
    keyring detection could activate a Secret Service or pick a plaintext
    backend before the vetting code exists.  A fresh interpreter is used so the
    module is really imported, and keyring's entry points are spied on.
    """
    script = textwrap.dedent(
        """
        import json
        import keyring.core

        calls = []
        keyring.core.init_backend = lambda *a, **k: calls.append("init")
        keyring.core.set_keyring = lambda *a, **k: calls.append("set")
        before = keyring.core._keyring_backend

        import barbaros.security  # noqa: F401

        print(json.dumps({
            "calls": calls,
            "before": before,
            "after": keyring.core._keyring_backend,
        }))
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])

    assert payload["calls"] == []
    assert payload["before"] is None  # no backend selected before the import
    assert payload["after"] is None  # ... and still none after it


def test_importing_security_does_not_register_more_backends():
    """The import must not add a backend class to keyring's registry.

    ``keyring`` selects the highest-priority registered backend.  Importing
    ``keyring.backends.chainer`` registers ``ChainerBackend`` (priority 10),
    which would then be selected instead of a working Secret Service - the
    storage module would refuse its own chain and disable key storage.  The test
    runs in a fresh interpreter and never calls ``keyring.get_keyring()``, so no
    real detection (and no session bus) is involved.
    """
    script = textwrap.dedent(
        """
        import json
        import sys

        import keyring.backend
        import keyring.core

        def registry_classes():
            return sorted(
                f"{klass.__module__}.{klass.__qualname__}"
                for klass in keyring.backend.KeyringBackend._classes
            )

        before_classes = registry_classes()
        before_selected = keyring.core._keyring_backend

        import barbaros.security  # noqa: F401

        print(json.dumps({
            "added": sorted(set(registry_classes()) - set(before_classes)),
            "chainer_imported": "keyring.backends.chainer" in sys.modules,
            "selection_changed": keyring.core._keyring_backend is not before_selected,
        }))
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])

    assert payload["added"] == []  # registry delta is what changes selection
    assert payload["chainer_imported"] is False  # never imported, not even lazily
    assert payload["selection_changed"] is False


# --- ApiKeyManager binding --------------------------------------------------


def test_keyring_store_satisfies_the_store_protocol():
    assert isinstance(KeyringSecretStore(), SecretStore)


def test_api_key_manager_uses_the_default_store_lazily(install_backend):
    """A standalone manager resolves the default keyring store on first use."""
    backend = install_backend(MemoryKeyring())
    manager = ApiKeyManager("acme")

    assert isinstance(manager.storage, SecretStorage)
    assert isinstance(manager.storage.store, KeyringSecretStore)
    assert manager.value() is None  # MISSING, not an exception

    assert manager.set("sk-lazy") is WriteStatus.PERSISTED
    assert backend.passwords[(SERVICE_NAME, "acme")] == "sk-lazy"
    assert manager.value() == "sk-lazy"
    assert manager.delete() is WriteStatus.PERSISTED
    assert manager.value() is None


def test_api_key_manager_bind_switches_stores():
    manager = ApiKeyManager("acme")
    first = RecordingStore(SecretStatus.MISSING)
    second = RecordingStore(SecretStatus.FOUND, value="bound-secret")

    manager.bind(SecretStorage(first))
    assert manager.value() is None

    manager.bind(SecretStorage(second))
    assert manager.value() == "bound-secret"
    assert manager.set("new-key") is WriteStatus.PERSISTED
    assert manager.delete() is WriteStatus.PERSISTED

    assert second.calls == [
        ("read", "acme"),
        ("write", "acme", "new-key"),
        ("delete", "acme"),
    ]
