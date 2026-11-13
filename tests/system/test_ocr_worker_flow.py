"""System tests for the OCR worker signal contract (BAR-25).

These tests drive the same Qt path the application uses - ``OCRWorker`` in a
``QThread`` with ``thread.started -> worker.run`` and signals delivered across
threads - instead of calling ``run_task`` directly.  The observable contract,
independent of the implementation, is:

* a client that does not prove image support -> ``acompletion`` is never called,
  exactly one ``error`` is emitted, ``done`` is not emitted, ``finished`` still
  fires (so the tab cannot stay in the progress state);
* a supported client -> the image is sent once and ``done`` fires once.
"""

from __future__ import annotations

import base64
import threading

from any_llm.types.completion import ChatCompletion
from PySide6.QtCore import QThread

from barbaros.widgets.filterable_combobox import ModelSelection
from barbaros.workers import OCRWorker

IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"


class StubClient:
    """any-llm client stand-in: records calls, never touches the network."""

    def __init__(
        self,
        *,
        supports_image: bool | None = True,
        failure: Exception | None = None,
    ):
        if supports_image is not None:
            self.SUPPORTS_COMPLETION_IMAGE = supports_image
        self.PROVIDER_NAME = "stub"
        self.failure = failure
        self.calls: list[tuple[str, list[dict]]] = []

    async def acompletion(self, model: str, messages: list[dict]) -> ChatCompletion:
        self.calls.append((model, messages))
        if self.failure is not None:
            raise self.failure
        return ChatCompletion(
            id="chatcmpl-system-test",
            created=0,
            model=model,
            object="chat.completion",
            choices=[],
        )


class StubProvider:
    def __init__(self, client: StubClient):
        self._client = client

    def client(self) -> StubClient:
        return self._client


def run_worker_in_thread(worker: OCRWorker, wait_until) -> tuple[list[str], list[ChatCompletion]]:
    """Run the worker through a real ``QThread`` and collect its signals."""
    errors: list[str] = []
    dones: list[ChatCompletion] = []
    finished = threading.Event()

    worker.error.connect(errors.append)
    worker.done.connect(dones.append)
    worker.finished.connect(finished.set)

    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(worker.deleteLater)
    thread.start()

    try:
        assert wait_until(finished.is_set), "worker never emitted finished"
        # Stop the thread from this (main) thread: a queued quit would never be
        # delivered while this thread blocks in ``wait()``.
        thread.quit()
        assert thread.wait(5_000), "worker thread did not stop after finished"
    finally:
        if thread.isRunning():
            thread.quit()
            thread.wait(5_000)

    return errors, dones


def make_worker(client: StubClient) -> OCRWorker:
    return OCRWorker(
        IMAGE_BYTES,
        ModelSelection(provider="acme", model="ocr-1"),
        StubProvider(client),
    )


def test_unsupported_provider_sends_no_image_and_reports_one_error(wait_until):
    client = StubClient(supports_image=False)

    errors, dones = run_worker_in_thread(make_worker(client), wait_until)

    assert client.calls == []
    assert dones == []
    assert len(errors) == 1


def test_client_without_support_flag_fails_closed(wait_until):
    client = StubClient(supports_image=None)

    errors, dones = run_worker_in_thread(make_worker(client), wait_until)

    assert client.calls == []
    assert dones == []
    assert len(errors) == 1


def test_supported_provider_sends_the_image_and_reports_done(wait_until):
    client = StubClient(supports_image=True)

    errors, dones = run_worker_in_thread(make_worker(client), wait_until)

    assert errors == []
    assert len(dones) == 1
    assert len(client.calls) == 1

    _, messages = client.calls[0]
    image_url = next(
        part["image_url"]["url"]
        for part in messages[0]["content"]
        if part["type"] == "image_url"
    )
    encoded = image_url.removeprefix("data:image/png;base64,")
    assert image_url != encoded, "image must travel as a base64 data URL"
    assert base64.b64decode(encoded) == IMAGE_BYTES


def test_acompletion_failure_reports_one_error_without_done(wait_until):
    client = StubClient(supports_image=True, failure=RuntimeError("provider exploded"))

    errors, dones = run_worker_in_thread(make_worker(client), wait_until)

    assert len(client.calls) == 1
    assert dones == []
    assert errors == ["provider exploded"]
