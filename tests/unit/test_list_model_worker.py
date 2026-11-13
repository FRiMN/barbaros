"""Contract tests for ``ListModelWorker`` timeout and cooperative cancellation (BAR-23).

The worker runs a bound on the whole provider request (``timeout``) and can be
cancelled from another thread.  The observable contract, independent of the
implementation, is:

* success -> exactly one ``finished(provider, json)`` and one terminal
  ``stopped()``, never ``error``;
* provider exception -> exactly one ``error(provider, message)`` and one
  ``stopped()``, never ``finished``;
* a hanging request -> one ``error`` whose text mentions the timeout, within
  the timeout budget, plus one ``stopped()``;
* cancellation -> no ``finished``, no ``error``, exactly one ``stopped()``, and
  the enclosing ``QThread`` finishes quickly;
* ``cancel()`` is idempotent and safe before ``run()`` and after completion.

These tests use a stub client, so no network is involved; the real any_llm
path is covered by ``tests/system/test_model_fetch_lifecycle.py``.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from any_llm import LLMProvider
from any_llm.types.model import Model
from PySide6.QtCore import QThread

from barbaros.model_manager import ProviderMeta
from barbaros.workers import ListModelWorker

PROVIDER = ProviderMeta("stub", LLMProvider.OLLAMA)
TIMEOUT = 0.2


# --- test doubles -----------------------------------------------------------


class StubClient:
    """any-llm client stand-in; optionally hangs until cancelled."""

    def __init__(
        self,
        *,
        models: list[Model] | None = None,
        failure: Exception | None = None,
        hang: bool = False,
    ):
        self._models = list(models or [])
        self.failure = failure
        self.hang = hang
        self.calls = 0
        self.started = threading.Event()
        self.cancelled = threading.Event()

    async def alist_models(self, **kwargs) -> list[Model]:
        self.calls += 1
        self.started.set()
        if self.hang:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        if self.failure is not None:
            raise self.failure
        return list(self._models)


class StubProvider:
    """The duck-typed provider surface ``ListModelWorker`` uses."""

    def __init__(self, client: StubClient):
        self.meta = PROVIDER
        self._client = client

    def client(self) -> StubClient:
        return self._client


class Recorder:
    """Collect the worker's terminal signals across threads."""

    def __init__(self, worker: ListModelWorker):
        self.finished: list[tuple[ProviderMeta, str]] = []
        self.errors: list[tuple[ProviderMeta, str]] = []
        self.stopped = 0
        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_error)
        worker.stopped.connect(self._on_stopped)

    def _on_finished(self, provider: ProviderMeta, payload: str) -> None:
        self.finished.append((provider, payload))

    def _on_error(self, provider: ProviderMeta, message: str) -> None:
        self.errors.append((provider, message))

    def _on_stopped(self) -> None:
        self.stopped += 1


def make_model(model_id: str) -> Model:
    return Model.model_validate(
        {"id": model_id, "created": 1_710_000_000, "object": "model", "owned_by": "stub"}
    )


def make_worker(client: StubClient, *, timeout: float | None = None) -> ListModelWorker:
    return ListModelWorker(StubProvider(client), timeout=timeout)


def start_in_thread(worker: ListModelWorker) -> QThread:
    """Run the worker through the same QThread path the manager uses."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.connect_terminate(thread)
    thread.start()
    return thread


def join_thread(thread: QThread) -> None:
    if thread.isRunning():
        thread.quit()
        thread.wait(5_000)


@pytest.fixture(autouse=True)
def _reset_main_event_loop():
    """Keep the closed loop from ``run()`` out of unrelated tests."""
    yield
    asyncio.set_event_loop(None)


# --- success / error --------------------------------------------------------


def test_success_emits_one_finished_and_one_stopped_without_error():
    client = StubClient(models=[make_model("alpha"), make_model("beta")])
    worker = make_worker(client)
    recorder = Recorder(worker)

    worker.run()

    assert recorder.errors == []
    assert len(recorder.finished) == 1
    assert recorder.stopped == 1
    provider, payload = recorder.finished[0]
    assert provider is PROVIDER
    assert json.loads(payload) == [
        {"id": "alpha", "created": 1_710_000_000, "object": "model", "owned_by": "stub"},
        {"id": "beta", "created": 1_710_000_000, "object": "model", "owned_by": "stub"},
    ]


def test_failure_emits_one_error_and_stopped_without_finished():
    client = StubClient(failure=RuntimeError("provider exploded"))
    worker = make_worker(client)
    recorder = Recorder(worker)

    worker.run()

    assert recorder.finished == []
    assert len(recorder.errors) == 1
    provider, message = recorder.errors[0]
    assert provider is PROVIDER
    assert message == "provider exploded"
    assert recorder.stopped == 1


# --- the total timeout ------------------------------------------------------


def test_hanging_fetch_times_out_with_one_error_within_the_budget():
    client = StubClient(hang=True)
    worker = make_worker(client, timeout=TIMEOUT)
    recorder = Recorder(worker)

    started_at = time.monotonic()
    worker.run()
    elapsed = time.monotonic() - started_at

    assert elapsed < 2.0, f"timeout did not bound the fetch: {elapsed:.2f}s"
    assert recorder.finished == []
    assert len(recorder.errors) == 1
    provider, message = recorder.errors[0]
    assert provider is PROVIDER
    assert "timeout" in message.lower(), message
    assert str(TIMEOUT) in message, message
    assert recorder.stopped == 1
    assert client.calls == 1


# --- cooperative cancellation ----------------------------------------------


def test_cancel_mid_flight_ends_the_thread_quickly_without_results():
    client = StubClient(hang=True)
    worker = make_worker(client)
    recorder = Recorder(worker)
    thread = start_in_thread(worker)
    try:
        assert client.started.wait(5.0), "stub fetch never started"
        cancelled_at = time.monotonic()
        worker.cancel()
        worker.cancel()  # idempotent
        assert thread.wait(1_000), "QThread did not stop within 1 s of cancel()"
        elapsed = time.monotonic() - cancelled_at
    finally:
        join_thread(thread)

    assert elapsed < 1.0, f"cancellation took {elapsed:.2f}s"
    assert recorder.finished == []
    assert recorder.errors == []
    assert recorder.stopped == 1
    assert client.cancelled.is_set()


def test_cancel_before_run_skips_the_fetch_and_emits_stopped():
    client = StubClient(models=[make_model("alpha")])
    worker = make_worker(client)
    recorder = Recorder(worker)

    worker.cancel()
    worker.cancel()
    worker.run()

    assert client.calls == 0, "a pre-cancelled worker must not fetch"
    assert recorder.finished == []
    assert recorder.errors == []
    assert recorder.stopped == 1


def test_cancel_before_thread_start_never_fetches():
    client = StubClient(models=[make_model("alpha")])
    worker = make_worker(client)
    recorder = Recorder(worker)

    worker.cancel()
    thread = start_in_thread(worker)
    try:
        assert thread.wait(1_000), "thread did not stop for a pre-cancelled worker"
    finally:
        join_thread(thread)

    assert client.calls == 0
    assert recorder.finished == []
    assert recorder.errors == []
    assert recorder.stopped == 1


def test_cancel_after_completion_is_a_noop():
    client = StubClient(models=[make_model("alpha")])
    worker = make_worker(client)
    recorder = Recorder(worker)

    worker.run()
    worker.cancel()
    worker.cancel()

    assert len(recorder.finished) == 1
    assert recorder.errors == []
    assert recorder.stopped == 1


def test_stopped_is_emitted_even_when_closing_the_loop_raises(monkeypatch):
    """The thread only quits on ``stopped``, so it must fire on every path."""
    client = StubClient(models=[make_model("alpha")])
    worker = make_worker(client)
    recorder = Recorder(worker)

    real_new_event_loop = asyncio.new_event_loop

    class NoCloseLoop:
        def __init__(self, loop):
            self._loop = loop

        def create_task(self, coro):
            return self._loop.create_task(coro)

        def run_until_complete(self, task):
            return self._loop.run_until_complete(task)

        def close(self):
            self._loop.close()
            raise RuntimeError("close failed")

    monkeypatch.setattr(
        asyncio, "new_event_loop", lambda: NoCloseLoop(real_new_event_loop())
    )

    with pytest.raises(RuntimeError, match="close failed"):
        worker.run()

    assert len(recorder.finished) == 1
    assert recorder.errors == []
    assert recorder.stopped == 1
