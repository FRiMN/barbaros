"""Unit tests for the worker signal contracts (BAR-25).

``OCRWorker`` must fail closed: when the client does not prove image support,
the image must never reach ``acompletion`` and the worker must report exactly
one error.  Before the fix the support check lived outside ``try`` and emitted
``error`` without ``return``, so the image was still sent and a missing
``SUPPORTS_COMPLETION_IMAGE`` attribute escaped ``run_task`` without any signal.
"""

from __future__ import annotations

import asyncio
import base64

from any_llm.types.completion import ChatCompletion

from barbaros.widgets.filterable_combobox import ModelSelection
from barbaros.workers import OCRWorker

IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"
EXPECTED_DATA_URL_PREFIX = "data:image/png;base64,"


# --- test doubles -----------------------------------------------------------


def completion() -> ChatCompletion:
    return ChatCompletion(
        id="chatcmpl-test",
        created=0,
        model="ocr-1",
        object="chat.completion",
        choices=[],
    )


class StubClient:
    """Minimal any-llm client stand-in exposing only the worker's contract."""

    def __init__(
        self,
        *,
        supports_image: bool = True,
        failure: Exception | None = None,
        provider_name: str | None = "stub",
    ):
        # ``supports_image=None`` omits the attribute entirely (unknown client).
        if supports_image is not None:
            self.SUPPORTS_COMPLETION_IMAGE = supports_image
        if provider_name is not None:
            self.PROVIDER_NAME = provider_name
        self.failure = failure
        self.calls: list[tuple[str, list[dict]]] = []

    async def acompletion(self, model: str, messages: list[dict]) -> ChatCompletion:
        self.calls.append((model, messages))
        if self.failure is not None:
            raise self.failure
        return completion()


class StubProvider:
    def __init__(self, client: StubClient):
        self._client = client

    def client(self) -> StubClient:
        return self._client


def make_worker(client: StubClient) -> OCRWorker:
    return OCRWorker(
        IMAGE_BYTES,
        ModelSelection(provider="acme", model="ocr-1"),
        StubProvider(client),
    )


def run_worker(worker: OCRWorker) -> tuple[list[str], list[ChatCompletion]]:
    """Run the worker's task and collect the emitted error/done payloads."""
    errors: list[str] = []
    dones: list[ChatCompletion] = []
    worker.error.connect(errors.append)
    worker.done.connect(dones.append)

    asyncio.run(worker.run_task())

    return errors, dones


# --- fail-closed: no image is sent unless support is proven ----------------


def test_unsupported_client_sends_no_image_and_emits_one_error():
    client = StubClient(supports_image=False)

    errors, dones = run_worker(make_worker(client))

    assert client.calls == []
    assert dones == []
    assert len(errors) == 1
    assert "acme" in errors[0]
    assert "does not support images" in errors[0]


def test_missing_support_attribute_is_treated_as_unsupported():
    """A client without the flag must fail closed, not silently hang."""
    client = StubClient(supports_image=None)

    errors, dones = run_worker(make_worker(client))

    assert client.calls == []
    assert dones == []
    assert len(errors) == 1


def test_missing_provider_name_does_not_break_the_error_path():
    client = StubClient(supports_image=False, provider_name=None)

    errors, dones = run_worker(make_worker(client))

    assert client.calls == []
    assert dones == []
    assert len(errors) == 1
    assert "unknown" in errors[0]


# --- the supported path still works ----------------------------------------


def test_supported_client_sends_the_image_once():
    client = StubClient(supports_image=True)

    errors, dones = run_worker(make_worker(client))

    assert errors == []
    assert len(dones) == 1
    assert len(client.calls) == 1

    model, messages = client.calls[0]
    assert model == "ocr-1"
    parts = messages[0]["content"]
    image_url = next(part["image_url"]["url"] for part in parts if part["type"] == "image_url")
    assert image_url.startswith(EXPECTED_DATA_URL_PREFIX)
    assert base64.b64decode(image_url.removeprefix(EXPECTED_DATA_URL_PREFIX)) == IMAGE_BYTES


def test_acompletion_failure_emits_error_without_done():
    client = StubClient(supports_image=True, failure=RuntimeError("provider exploded"))

    errors, dones = run_worker(make_worker(client))

    assert dones == []
    assert errors == ["provider exploded"]
