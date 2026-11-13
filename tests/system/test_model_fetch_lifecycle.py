"""System tests for the model-fetch lifecycle against a real, hung HTTP endpoint (BAR-23).

The app fetches provider model lists on background ``QThread``s.  A stalled
endpoint must not hang the GUI: stopping or quitting cancels the fetch
cooperatively within a bounded budget, and an unattended fetch times out on its
own.  These tests use a real local HTTP server (127.0.0.1, ephemeral port) and
the real ``any_llm`` client, so the whole path - Qt thread, asyncio loop, httpx
request - is exercised.  The "hang" server accepts the request and never
answers; the "ready" server behaves like a well-behaved provider.  No real
network is used.

The asserted contract is observable: elapsed time, emitted Qt signals, finished
threads, and the manager's public ``fetching_models_active_workers`` property.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from any_llm import LLMProvider
from PySide6.QtCore import QThread, QTimer

from barbaros.model_manager import ModelManager, ProviderClient, ProviderMeta
from barbaros.workers import ListModelWorker

READY_MODELS = [
    {"id": "fake-1", "object": "model", "created": 1_710_000_000, "owned_by": "fake"},
    {"id": "fake-2", "object": "model", "created": 1_710_000_001, "owned_by": "fake"},
]
REQUEST_DEADLINE_S = 5.0
STOP_DEADLINE_S = 2.0
TIMEOUT_BUDGET_S = 3.0


# --- local fake provider server ---------------------------------------------


class _ServerState:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.requests = 0
        self.request_seen = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()


class _ModelHandler(BaseHTTPRequestHandler):
    """``ready``: return the model list; ``hang``: accept and never answer."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        state: _ServerState = self.server.state
        with state.lock:
            state.requests += 1
        state.request_seen.set()

        if state.mode == "hang":
            state.release.wait(30)  # teardown unblocks every handler
            return

        body = json.dumps({"object": "list", "data": READY_MODELS}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        pass


@pytest.fixture(autouse=True)
def _local_network_only(monkeypatch):
    """Keep httpx from routing the fake 127.0.0.1 endpoint through a proxy."""
    for variable in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(variable, raising=False)
    for variable in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(variable, "127.0.0.1,localhost")


@pytest.fixture
def model_server():
    """Start local fake providers; teardown always releases blocked handlers."""
    servers: list[tuple[ThreadingHTTPServer, threading.Thread, _ServerState]] = []

    def start(mode: str = "hang") -> tuple[int, _ServerState]:
        state = _ServerState(mode)
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelHandler)
        server.state = state
        server.daemon_threads = True
        thread = threading.Thread(
            target=server.serve_forever, name=f"fake-model-server-{mode}", daemon=True
        )
        thread.start()
        servers.append((server, thread, state))
        return server.server_address[1], state

    yield start

    for server, thread, state in servers:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --- helpers ----------------------------------------------------------------


def make_meta(port: int, name: str) -> ProviderMeta:
    meta = ProviderMeta(name, LLMProvider.OPENAI, api_base=f"http://127.0.0.1:{port}")
    meta.api_key_manager.set("test-key")  # the autouse fake keyring stores it
    return meta


class SignalRecord:
    """Collect the worker signals delivered across threads."""

    def __init__(self, worker: ListModelWorker):
        self.finished: list[str] = []
        self.errors: list[str] = []
        self.stopped = 0
        worker.finished.connect(lambda provider, payload: self.finished.append(payload))
        worker.error.connect(lambda provider, message: self.errors.append(message))
        worker.stopped.connect(self._on_stopped)

    def _on_stopped(self) -> None:
        self.stopped += 1


def start_manager_fetch(manager: ModelManager, meta: ProviderMeta):
    """Start a fetch through the manager and return its tracked worker/thread."""
    manager._start_fetching_models(manager[meta])
    return manager._fetching_models_workers[meta.name]


# --- (a) stopping a hung fetch ----------------------------------------------


def test_stop_of_a_hung_fetch_is_bounded_and_ends_the_thread(model_server, wait_until):
    port, state = model_server("hang")
    manager = ModelManager()
    meta = make_meta(port, "hung-stop")
    manager.add(meta)
    manager_errors: list[str] = []
    manager.error.connect(manager_errors.append)
    worker, thread = start_manager_fetch(manager, meta)
    record = SignalRecord(worker)

    try:
        assert wait_until(state.request_seen.is_set, timeout=REQUEST_DEADLINE_S), (
            "the fake provider never received the model-list request"
        )

        started_at = time.monotonic()
        manager.stop_fetching_models(meta.name)
        elapsed = time.monotonic() - started_at

        assert elapsed < STOP_DEADLINE_S, f"stop of a hung fetch took {elapsed:.2f}s"
        assert thread.isFinished(), "the cancelled fetch thread must finish"
        assert record.finished == []
        assert record.errors == [], "user-initiated cancellation is not an error"
        assert manager_errors == [], "cancellation must not raise a provider error"
        assert record.stopped == 1
        assert manager.fetching_models_active_workers == []
    finally:
        manager.shutdown()


# --- (b) shutdown with several hung providers -------------------------------


def test_shutdown_with_hung_fetches_is_bounded_clean_and_idempotent(model_server, wait_until):
    port, state = model_server("hang")
    manager = ModelManager()
    metas = [make_meta(port, f"hung-{index}") for index in range(3)]
    manager_errors: list[str] = []
    manager.error.connect(manager_errors.append)

    records: list[SignalRecord] = []
    tracked: list[tuple[ListModelWorker, QThread]] = []
    try:
        for meta in metas:
            manager.add(meta)
        for meta in metas:
            worker, thread = start_manager_fetch(manager, meta)
            records.append(SignalRecord(worker))
            tracked.append((worker, thread))

        assert wait_until(lambda: state.requests >= len(metas), timeout=REQUEST_DEADLINE_S), (
            "not every fake provider received its request"
        )

        started_at = time.monotonic()
        manager.shutdown()
        elapsed = time.monotonic() - started_at

        assert elapsed < STOP_DEADLINE_S, f"shutdown of hung fetches took {elapsed:.2f}s"
        assert all(thread.isFinished() for _, thread in tracked)
        assert manager.fetching_models_active_workers == []
        assert manager_errors == [], "cancellation must not raise provider errors"
        assert all(record.errors == [] for record in records)
        assert all(record.finished == [] for record in records)
        assert [record.stopped for record in records] == [1, 1, 1]

        # Idempotent: the second quit is a fast no-op.
        started_at = time.monotonic()
        manager.shutdown()
        assert time.monotonic() - started_at < 1.0

        # The GUI is still alive: its event loop must keep processing events.
        processed: list[int] = []
        QTimer.singleShot(0, lambda: processed.append(1))
        assert wait_until(lambda: processed, timeout=2.0), "the Qt event loop did not process events"
    finally:
        manager.shutdown()


# --- (c) an unattended hung fetch times out on its own ----------------------


def test_hung_endpoint_without_stop_times_out_and_reports_one_error(model_server, wait_until):
    port, state = model_server("hang")
    meta = make_meta(port, "timeout")
    worker = ListModelWorker(ProviderClient(meta=meta, models=[]), timeout=0.5)
    record = SignalRecord(worker)

    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.connect_terminate(thread)
    started_at = time.monotonic()
    thread.start()
    try:
        assert wait_until(state.request_seen.is_set, timeout=REQUEST_DEADLINE_S), (
            "the fake provider never received the model-list request"
        )
        assert wait_until(thread.isFinished, timeout=REQUEST_DEADLINE_S), (
            "the worker did not finish after its timeout"
        )
        elapsed = time.monotonic() - started_at
    finally:
        if thread.isRunning():
            thread.quit()
            thread.wait(5_000)

    assert elapsed < TIMEOUT_BUDGET_S, f"timed-out fetch took {elapsed:.2f}s"
    assert record.finished == []
    assert len(record.errors) == 1
    assert "timeout" in record.errors[0].lower(), record.errors[0]
    assert "0.5" in record.errors[0], record.errors[0]
    assert record.stopped == 1


# --- (d) a responsive endpoint still delivers models ------------------------


def test_answering_endpoint_still_delivers_models_through_the_manager(model_server, wait_until):
    port, _state = model_server("ready")
    manager = ModelManager()
    meta = make_meta(port, "ready")
    manager_errors: list[str] = []
    manager.error.connect(manager_errors.append)
    manager.add(meta)

    try:
        manager.start_fetching_models()

        assert wait_until(
            lambda: [model.id for model in manager[meta].models] == ["fake-1", "fake-2"],
            timeout=REQUEST_DEADLINE_S,
        ), "the fetched models never reached the manager"
        assert manager_errors == []
        assert wait_until(
            lambda: manager.fetching_models_active_workers == [],
            timeout=REQUEST_DEADLINE_S,
        ), "the fetch thread did not finish after a successful response"
    finally:
        manager.shutdown()
