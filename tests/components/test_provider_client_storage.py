"""Component tests for ``ProviderClient.client()`` key handling (BAR-11, issue #9).

The store reports LOCKED/UNAVAILABLE/CORRUPT when it cannot tell whether a key
exists.  Only a *local* runtime that needs no API key (``KEYLESS_PROVIDER_TYPES``:
ollama, llama.cpp, llamafile, LM Studio, vLLM) is probed without a key and keeps
working; a cloud provider is never probed keyless - its keyless constructor is
slow and side-effectful (AWS credential chain, Google ADC, ...) and would freeze
the GUI on the degraded path.  A cloud provider therefore fails fast with the
typed ``SecretStorageError``.

For the local runtimes, any creation failure without the key (``MissingApiKeyError``,
``ValueError`` for a missing api_base, missing credentials, ...) is reported as
the typed storage failure; only ``BaseException`` (``KeyboardInterrupt``) escapes.

``AnyLLM.create`` is the only external boundary replaced here (by a recorder);
everything else is the real ``ProviderClient``/``ProviderMeta``/
``ApiKeyManager``/``SecretStorage`` stack.  No network, D-Bus or real keyring is
involved.
"""

from __future__ import annotations

import pytest
from any_llm import LLMProvider
from any_llm.exceptions import MissingApiKeyError

import barbaros.model_manager as model_manager_module
from barbaros.model_manager import (
    KEYLESS_PROVIDER_TYPES,
    ProviderClient,
    ProviderMeta,
)
from barbaros.security import (
    SERVICE_NAME,
    Availability,
    SecretRead,
    SecretStatus,
    SecretStorage,
    SecretStorageError,
    WriteStatus,
)

SENTINEL = object()


# --- test doubles -----------------------------------------------------------


def record_create(monkeypatch) -> list[tuple]:
    """Replace ``AnyLLM.create`` with a recorder returning a sentinel client."""
    calls: list[tuple] = []

    def create(*args, **kwargs):
        calls.append((args, kwargs))
        return SENTINEL

    monkeypatch.setattr(model_manager_module.AnyLLM, "create", create)
    return calls


def raise_from_create(monkeypatch, error: BaseException) -> list[tuple]:
    """Make the keyless ``AnyLLM.create`` attempt fail with ``error``."""
    calls: list[tuple] = []

    def create(provider_type, api_key=None, api_base=None, **kwargs):
        calls.append((provider_type, api_key, api_base))
        raise error

    monkeypatch.setattr(model_manager_module.AnyLLM, "create", create)
    return calls


class FailingStore:
    """Store whose reads fail with a fixed typed status."""

    def __init__(self, status: SecretStatus):
        self.status = status

    def availability(self, *, refresh: bool = False) -> Availability:
        return Availability.READY

    def read(self, provider_name: str) -> SecretRead:
        return SecretRead(self.status)

    def write(self, provider_name: str, value: str) -> WriteStatus:
        return WriteStatus.ERROR

    def delete(self, provider_name: str) -> WriteStatus:
        return WriteStatus.ERROR


def provider_client(
    provider_type: LLMProvider,
    *,
    api_base: str | None = None,
    status: SecretStatus | None = None,
) -> ProviderClient:
    """A real ``ProviderClient``; optionally bound to a failing store."""
    meta = ProviderMeta("acme", provider_type, api_base)
    if status is not None:
        meta.api_key_manager.bind(SecretStorage(FailingStore(status)))
    return ProviderClient(meta=meta, models=[])


LOCAL_PROVIDER_TYPES = [
    LLMProvider.OLLAMA,
    LLMProvider.LLAMACPP,
    LLMProvider.LLAMAFILE,
    LLMProvider.LMSTUDIO,
    LLMProvider.VLLM,
]
CLOUD_PROVIDER_TYPES = [
    LLMProvider.OPENAI,
    LLMProvider.BEDROCK,
    LLMProvider.VERTEXAI,
    LLMProvider.OTARI,
]
STORAGE_FAILURES = [
    SecretStatus.LOCKED,
    SecretStatus.UNAVAILABLE,
    SecretStatus.CORRUPT,
]


# --- the fail-fast policy itself --------------------------------------------


def test_keyless_provider_types_are_the_local_runtimes():
    """The allowlist is exactly the local runtimes; membership is a policy."""
    assert set(KEYLESS_PROVIDER_TYPES) == set(LOCAL_PROVIDER_TYPES)


@pytest.mark.parametrize("provider_type", LOCAL_PROVIDER_TYPES)
def test_local_provider_is_considered_keyless(provider_type):
    assert provider_type in KEYLESS_PROVIDER_TYPES


@pytest.mark.parametrize("provider_type", CLOUD_PROVIDER_TYPES)
def test_cloud_provider_is_not_considered_keyless(provider_type):
    assert provider_type not in KEYLESS_PROVIDER_TYPES


# --- keyless providers survive a storage failure ----------------------------


def test_keyless_provider_gets_a_keyless_client_when_keyring_is_unavailable(
    no_keyring, monkeypatch
):
    """A local provider must not be blocked just because the keyring is down."""
    calls = record_create(monkeypatch)

    client = provider_client(LLMProvider.OLLAMA).client()

    assert client is SENTINEL
    assert calls == [((LLMProvider.OLLAMA, None, None), {})]


@pytest.mark.parametrize("status", STORAGE_FAILURES)
def test_keyless_provider_gets_a_client_for_every_storage_failure(status, monkeypatch):
    calls = record_create(monkeypatch)

    client = provider_client(LLMProvider.OLLAMA, status=status).client()

    assert client is SENTINEL
    assert calls == [((LLMProvider.OLLAMA, None, None), {})]


@pytest.mark.parametrize(
    ("provider_type", "probed_keyless"),
    [
        pytest.param(LLMProvider.OLLAMA, True, id="ollama"),
        pytest.param(LLMProvider.VLLM, True, id="vllm"),
        pytest.param(LLMProvider.OPENAI, False, id="openai"),
        pytest.param(LLMProvider.BEDROCK, False, id="bedrock"),
        pytest.param(LLMProvider.VERTEXAI, False, id="vertexai"),
    ],
)
def test_keyless_client_is_attempted_only_for_local_providers(
    provider_type, probed_keyless, no_keyring, monkeypatch
):
    """Cloud providers fail fast: ``AnyLLM.create`` must not be called at all."""
    calls = record_create(monkeypatch)

    if probed_keyless:
        assert provider_client(provider_type).client() is SENTINEL
        assert calls == [((provider_type, None, None), {})]
        return

    with pytest.raises(SecretStorageError) as excinfo:
        provider_client(provider_type).client()

    assert excinfo.value.status is SecretStatus.UNAVAILABLE
    assert calls == []


# --- cloud providers report the storage failure without a probe -------------


def test_key_requiring_provider_reraises_the_typed_storage_error(
    no_keyring, monkeypatch
):
    """OpenAI under an unavailable keyring: typed error, and no slow probe."""
    calls = record_create(monkeypatch)

    with pytest.raises(SecretStorageError) as excinfo:
        provider_client(LLMProvider.OPENAI).client()

    assert calls == []  # no keyless AnyLLM.create attempt
    assert excinfo.value.status is SecretStatus.UNAVAILABLE
    # The user-facing typed message, not any_llm's "no API key" wording.
    assert str(excinfo.value) == str(SecretStorageError(SecretStatus.UNAVAILABLE))


@pytest.mark.parametrize("provider_type", CLOUD_PROVIDER_TYPES)
@pytest.mark.parametrize("status", STORAGE_FAILURES)
def test_cloud_provider_fails_fast_for_every_storage_status(
    provider_type, status, monkeypatch
):
    """No keyless attempt is made for any cloud provider, for any failure status."""
    calls = record_create(monkeypatch)

    with pytest.raises(SecretStorageError) as excinfo:
        provider_client(provider_type, status=status).client()

    assert excinfo.value.status is status
    assert calls == []


# --- local providers: keyless creation errors become the typed failure -----


@pytest.mark.parametrize("provider_type", [LLMProvider.OLLAMA, LLMProvider.VLLM])
@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ValueError("api_base is required"), id="value-error"),
        pytest.param(
            MissingApiKeyError("ollama", "OLLAMA_API_KEY"), id="missing-api-key"
        ),
    ],
)
def test_keyless_creation_errors_are_converted_to_the_typed_storage_error(
    provider_type, error, no_keyring, monkeypatch
):
    """Exotic providers raise ValueError/DefaultCredentialsError, not only MissingApiKeyError."""
    calls = raise_from_create(monkeypatch, error)

    with pytest.raises(SecretStorageError) as excinfo:
        provider_client(provider_type).client()

    assert calls == [(provider_type, None, None)]
    assert excinfo.value.status is SecretStatus.UNAVAILABLE
    assert str(excinfo.value) == str(SecretStorageError(SecretStatus.UNAVAILABLE))


def test_base_exceptions_from_keyless_creation_still_propagate(
    no_keyring, monkeypatch
):
    """Only ``Exception`` is converted: ``KeyboardInterrupt`` must escape."""
    calls = raise_from_create(monkeypatch, KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        provider_client(LLMProvider.OLLAMA).client()

    assert calls == [(LLMProvider.OLLAMA, None, None)]


# --- the unchanged paths: MISSING and FOUND ---------------------------------


def test_missing_key_still_passes_none_without_raising(fake_keyring, monkeypatch):
    """No stored key is not a storage failure: any_llm gets ``None`` as before."""
    calls = record_create(monkeypatch)

    client = provider_client(LLMProvider.OPENAI, api_base="http://localhost:1").client()

    assert client is SENTINEL
    assert calls == [((LLMProvider.OPENAI, None, "http://localhost:1"), {})]


def test_found_key_is_passed_unchanged(fake_keyring, monkeypatch):
    secret = "sk-BAR11-FOUND-KEY"
    fake_keyring.set_password(SERVICE_NAME, "acme", secret)
    calls = record_create(monkeypatch)

    provider_client(LLMProvider.OPENAI).client()

    assert calls == [((LLMProvider.OPENAI, secret, None), {})]
