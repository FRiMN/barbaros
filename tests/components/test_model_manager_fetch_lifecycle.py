"""Component tests for bounded, cooperative model-fetch stop/shutdown (BAR-23).

The GUI must never block indefinitely on a model fetch: stopping a fetch
(Reload, remove a provider, quit) cancels the worker cooperatively and waits for
the thread with a bounded timeout.  ``QThread.terminate()`` must never be used.

These tests drive a real ``ModelManager``; the provider client is a stub whose
``alist_models`` hangs until cancelled, so no network is involved.  A ``FakeThread``
double that ignores cancellation covers the pathological case: the manager must
still return within its budget and log a warning.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
import time
import weakref

import pytest
from any_llm import LLMProvider
from any_llm.types.model import Model
from PySide6.QtCore import QObject, Signal

from barbaros.model_manager import (
    SHUTDOWN_BUDGET_MS,
    STOP_WAIT_MS,
    ModelManager,
    ProviderMeta,
)

FETCH_START_DEADLINE_S = 5.0
#: Generous margin over the documented budget: the assertion guards the order of
#: magnitude (GUI must not hang), not milliseconds.
STOP_DEADLINE_S = 2.0


# --- test doubles -----------------------------------------------------------


class FakeStore:
    """In-memory ``load``/``save`` port for the manager's cache."""

    def __init__(self) -> None:
        self._data: dict[str, list[dict]] = {}
        self.save_calls = 0

    @property
    def data(self) -> dict[str, list[dict]]:
        return dict(self._data)

    def load(self) -> dict[str, list[dict]]:
        return {name: list(models) for name, models in self._data.items()}

    def save(self, models: dict[str, list[dict]]) -> bool:
        self.save_calls += 1
        self._data = {name: list(entries) for name, entries in models.items()}
        return True


class HangingClient:
    """any-llm client stand-in: never answers, records cancellation."""

    def __init__(self) -> None:
        self.calls = 0
        self.started = threading.Event()
        self.cancelled = threading.Event()

    async def alist_models(self, **kwargs) -> list:
        self.calls += 1
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class StubProvider:
    """Duck-typed provider: every ``client()`` call returns a fresh hanging client."""

    def __init__(self, meta: ProviderMeta):
        self.meta = meta
        self.clients: list[HangingClient] = []

    def client(self) -> HangingClient:
        client = HangingClient()
        self.clients.append(client)
        return client


class FakeThread:
    """A thread that ignores cancellation: ``wait()`` always reports a timeout."""

    def __init__(self) -> None:
        self.waits: list[int] = []
        self.terminate_calls = 0

    def isRunning(self) -> bool:
        return True

    def isFinished(self) -> bool:
        return False

    def wait(self, msecs: int = -1, **kwargs) -> bool:
        self.waits.append(msecs)
        return False

    def terminate(self) -> None:
        self.terminate_calls += 1
        raise AssertionError("QThread.terminate() must never be called (BAR-23)")

    def quit(self) -> None:
        pass


class FakeWorker(QObject):
    """Worker double with the real terminal signals (disconnected on stop)."""

    finished = Signal(ProviderMeta, str)
    error = Signal(ProviderMeta, str)
    stopped = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1


class DelayedClient:
    """Answers after a short delay, so its result can be queued but not yet applied."""

    def __init__(self, models: list[Model], *, delay: float = 0.05):
        self._models = list(models)
        self.delay = delay
        self.started = threading.Event()

    async def alist_models(self, **kwargs) -> list[Model]:
        self.started.set()
        await asyncio.sleep(self.delay)
        return list(self._models)


class DelayedFailingClient:
    """Fails after a short delay, so its error can be queued but not yet applied."""

    def __init__(self, *, delay: float = 0.05, message: str = "provider failed"):
        self.delay = delay
        self.message = message
        self.started = threading.Event()
        self.calls = 0

    async def alist_models(self, **kwargs) -> list[Model]:
        self.calls += 1
        self.started.set()
        await asyncio.sleep(self.delay)
        raise RuntimeError(self.message)


class FixedProvider:
    """Duck-typed provider returning one already-created client."""

    def __init__(self, meta: ProviderMeta, client: DelayedClient):
        self.meta = meta
        self._client = client

    def client(self) -> DelayedClient:
        return self._client


# --- helpers ----------------------------------------------------------------


def make_meta(name: str = "p1") -> ProviderMeta:
    return ProviderMeta(name, LLMProvider.OLLAMA)


def make_model(model_id: str) -> Model:
    return Model.model_validate(
        {"id": model_id, "created": 1_710_000_000, "object": "model", "owned_by": "stub"}
    )


def track_fake_pair(manager: ModelManager, name: str) -> tuple[FakeWorker, FakeThread]:
    """Inject a tracked hanging (worker, thread) that ignores cancellation.

    Result delivery is not exercised here: the real fetch lifecycle is covered
    separately; these doubles only verify the bounded stop/shutdown mechanism.
    """
    worker = FakeWorker()
    thread = FakeThread()
    manager._fetching_models_workers[name] = (worker, thread)
    return worker, thread


def start_fetch(manager: ModelManager, provider: StubProvider) -> HangingClient:
    """Start a real fetch through the manager and wait until it reaches the client."""
    manager._start_fetching_models(provider)
    client = provider.clients[-1]
    assert client.started.wait(FETCH_START_DEADLINE_S), "fetch never reached the stub client"
    return client


def tracked(manager: ModelManager, name: str):
    """The manager's (worker, thread) pair for ``name``.

    ``_fetching_models_workers`` is the manager's internal tracking table; the
    test needs the real ``QThread`` to assert it finished.  Behavioural
    assertions below use the public ``fetching_models_active_workers``.
    """
    return manager._fetching_models_workers[name]


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def manager(store: FakeStore):
    model_manager = ModelManager(cache=store)
    yield model_manager
    model_manager.shutdown()  # never leave a thread behind, even on failure


# --- stop: cancel + bounded wait, never terminate ---------------------------


def test_stop_cancels_waits_with_a_timeout_and_never_terminates(manager, monkeypatch):
    meta = make_meta()
    manager.add(meta)
    provider = StubProvider(meta)
    client = start_fetch(manager, provider)
    worker, thread = tracked(manager, meta.name)

    cancel_calls: list[int] = []
    real_cancel = worker.cancel

    def recording_cancel() -> None:
        cancel_calls.append(1)
        real_cancel()

    monkeypatch.setattr(worker, "cancel", recording_cancel)

    wait_budgets: list[int] = []
    real_wait = thread.wait

    def recording_wait(*args, **kwargs) -> bool:
        wait_budgets.append(args[0] if args else kwargs.get("msecs", -1))
        return real_wait(*args, **kwargs)

    monkeypatch.setattr(thread, "wait", recording_wait)
    monkeypatch.setattr(
        thread,
        "terminate",
        lambda *args, **kwargs: pytest.fail("QThread.terminate() must never be called"),
    )

    started_at = time.monotonic()
    manager.stop_fetching_models(meta.name)
    elapsed = time.monotonic() - started_at

    assert cancel_calls == [1], "stop must request cooperative cancellation"
    assert wait_budgets, "stop must wait for the thread"
    assert 0 < wait_budgets[0] <= STOP_WAIT_MS, wait_budgets
    assert elapsed < STOP_DEADLINE_S, f"stop took {elapsed:.2f}s"
    assert thread.isFinished(), "the cancelled worker thread must finish"
    assert manager.fetching_models_active_workers == []
    assert client.cancelled.is_set()


def test_stop_returns_within_budget_when_the_thread_ignores_cancellation(manager, caplog):
    worker, thread = track_fake_pair(manager, "stubborn")
    worker_ref = weakref.ref(worker)
    thread_ref = weakref.ref(thread)

    with caplog.at_level(logging.WARNING, logger="barbaros.model_manager"):
        started_at = time.monotonic()
        manager.stop_fetching_models("stubborn")
        elapsed = time.monotonic() - started_at

    assert elapsed < 1.0, f"stop blocked for {elapsed:.2f}s on a non-stopping thread"
    assert worker.cancel_calls == 1
    assert thread.waits, "the manager must wait with a bounded timeout"
    assert 0 < thread.waits[0] <= STOP_WAIT_MS
    assert thread.terminate_calls == 0, "terminate() must never be used"
    assert any(record.levelno == logging.WARNING for record in caplog.records), (
        "a thread that does not stop must be logged as a warning"
    )
    assert manager.fetching_models_active_workers == []

    # A worker that outlived its budget owns a still-running QThread: the
    # manager must keep both alive until the thread is destroyed.
    retired = manager._retiring_workers
    assert len(retired) == 1, retired
    assert retired[0][0] is worker
    assert retired[0][1] is thread

    del worker, thread
    gc.collect()
    assert worker_ref() is not None, "the retiring worker must not be garbage-collected"
    assert thread_ref() is not None, "the retiring QThread must not be garbage-collected"


def test_stop_accepts_an_explicit_wait_budget(manager):
    _worker, thread = track_fake_pair(manager, "p1")

    manager.stop_fetching_models("p1", wait_ms=25)

    assert thread.waits == [25]


def test_stop_of_an_untracked_provider_is_a_noop(manager):
    started_at = time.monotonic()
    manager.stop_fetching_models("does-not-exist")
    assert time.monotonic() - started_at < 0.5


# --- results queued by a fetch that is then stopped -------------------------


def test_stop_drops_a_result_that_was_already_queued(manager, wait_until):
    """A result delivered after the user stopped the fetch must never be applied.

    The fetch completes in its worker thread while this thread does not run its
    event loop, so the queued ``finished`` delivery is still pending.  Stopping
    the fetch must detach the worker, and draining the queue must not resurrect
    the stale model list (or raise a provider error) for a fetch the user just
    stopped - the Reload path.
    """
    meta = make_meta()
    manager.add(meta)
    client = DelayedClient([make_model("stale")])
    manager_errors: list[str] = []
    manager.error.connect(manager_errors.append)
    manager._start_fetching_models(FixedProvider(meta, client))
    _worker, thread = tracked(manager, meta.name)

    # Finish the fetch without processing this thread's event queue.
    assert client.started.wait(FETCH_START_DEADLINE_S), "the fetch never reached the client"
    assert thread.wait(2_000), "the fetch thread did not finish"
    assert manager[meta].models == [], "the queued result must not be applied before events run"

    manager.stop_fetching_models(meta.name)

    # Drain the event queue: the queued result of the stopped fetch must drop.
    wait_until(lambda: False, timeout=0.3)

    assert [model.id for model in manager[meta].models] == []
    assert manager_errors == []


def test_stop_drops_an_error_from_a_stopped_worker(manager, wait_until):
    """A provider error queued before the stop must not raise a dialog (BAR-23).

    Symmetric to the stale-result case: the worker fails right after the fetch
    is stopped, so its ``error`` is still pending when the manager drops the
    worker from tracking.
    """
    meta = make_meta()
    manager.add(meta)
    client = DelayedFailingClient()
    manager_errors: list[str] = []
    manager.error.connect(manager_errors.append)
    manager._start_fetching_models(FixedProvider(meta, client))
    _worker, thread = tracked(manager, meta.name)

    assert client.started.wait(FETCH_START_DEADLINE_S), "the fetch never reached the client"
    assert thread.wait(2_000), "the failing fetch thread did not finish"

    manager.stop_fetching_models(meta.name)
    wait_until(lambda: False, timeout=0.3)

    assert manager_errors == [], "an error from a stopped fetch must be dropped"


def test_error_of_the_current_fetch_is_still_delivered(manager, wait_until):
    """Positive control: the identity guard must not swallow real fetch failures."""
    meta = make_meta()
    manager.add(meta)
    manager_errors: list[str] = []
    manager.error.connect(manager_errors.append)

    manager._start_fetching_models(FixedProvider(meta, DelayedFailingClient(delay=0)))

    assert wait_until(lambda: bool(manager_errors), timeout=FETCH_START_DEADLINE_S), (
        "a provider failure of the tracked fetch was not reported"
    )
    assert len(manager_errors) == 1
    assert "provider failed" in manager_errors[0]


# --- shutdown: one global, bounded, idempotent deadline ---------------------


def test_stop_workers_uses_one_shared_deadline(manager):
    """A batch stop of N workers is bounded by one deadline, not N budgets (BAR-23)."""

    class SleepingThread(FakeThread):
        """A thread that actually spends the wait budget it is given."""

        def wait(self, msecs: int = -1, **kwargs) -> bool:
            self.waits.append(msecs)
            time.sleep(max(0, msecs) / 1000)
            return False

    pairs: dict[str, tuple[FakeWorker, FakeThread]] = {}
    for name in ("a", "b", "c"):
        worker, thread = FakeWorker(), SleepingThread()
        manager._fetching_models_workers[name] = (worker, thread)
        pairs[name] = (worker, thread)

    budget_ms = 200
    started_at = time.monotonic()
    manager._stop_workers(list(pairs), budget_ms)
    elapsed = time.monotonic() - started_at

    assert elapsed < budget_ms / 1000 + 0.3, f"batch stop took {elapsed:.2f}s"
    first_budget = pairs["a"][1].waits[0]
    assert abs(first_budget - budget_ms) <= 10, first_budget
    assert all(thread.terminate_calls == 0 for _worker, thread in pairs.values())
    assert manager.fetching_models_active_workers == []


def test_shutdown_is_bounded_idempotent_and_cleans_all_workers(manager):
    pairs = {name: track_fake_pair(manager, name) for name in ("p1", "p2")}

    started_at = time.monotonic()
    manager.shutdown()
    elapsed = time.monotonic() - started_at

    assert elapsed < SHUTDOWN_BUDGET_MS / 1000 + 0.5, f"shutdown took {elapsed:.2f}s"
    for worker, thread in pairs.values():
        assert worker.cancel_calls == 1
        assert thread.terminate_calls == 0
    assert manager.fetching_models_active_workers == []
    assert manager._fetching_models_workers == {}

    # Idempotent: a second quit must be a fast no-op, not an exception.
    started_at = time.monotonic()
    manager.shutdown()
    assert time.monotonic() - started_at < 1.0


# --- remove / reload with an active fetch -----------------------------------


def test_remove_with_active_fetch_is_bounded_and_leaves_consistent_state(
    manager, store, monkeypatch
):
    meta = make_meta()
    manager.add(meta)
    provider = StubProvider(meta)
    client = start_fetch(manager, provider)
    _, thread = tracked(manager, meta.name)
    monkeypatch.setattr(
        thread,
        "terminate",
        lambda *args, **kwargs: pytest.fail("QThread.terminate() must never be called"),
    )
    removed: list[str] = []
    manager.removed.connect(removed.append)

    started_at = time.monotonic()
    manager.remove(meta.name)
    elapsed = time.monotonic() - started_at

    assert elapsed < STOP_DEADLINE_S, f"remove took {elapsed:.2f}s"
    assert meta.name not in manager
    assert removed == [meta.name]
    assert store.save_calls >= 1
    assert meta.name not in store.data
    assert manager.fetching_models_active_workers == []
    assert client.cancelled.is_set()
    assert thread.isFinished()


def test_reload_cancels_the_previous_fetch_and_tracks_the_new_one(manager):
    meta = make_meta()
    manager.add(meta)
    provider = StubProvider(meta)
    first_client = start_fetch(manager, provider)
    first_worker, first_thread = tracked(manager, meta.name)

    manager._start_fetching_models(provider)
    second_client = provider.clients[-1]
    assert second_client is not first_client
    assert second_client.started.wait(FETCH_START_DEADLINE_S), "reloaded fetch never started"
    second_worker, second_thread = tracked(manager, meta.name)

    assert second_worker is not first_worker
    assert second_thread is not first_thread
    assert first_thread.isFinished(), "the previous fetch must be stopped"
    assert first_client.cancelled.is_set()
    assert manager.fetching_models_active_workers == [meta.name]
