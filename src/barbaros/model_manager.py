from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING

from any_llm import AnyLLM, LLMProvider
from any_llm.types.model import Model
from dataclasses_json import dataclass_json
from psygnal import Signal
from PySide6.QtCore import QObject, Qt, QThread, Slot

from barbaros.provider_models import model_entries
from barbaros.security import KeySecurityManager

if TYPE_CHECKING:
    from barbaros.model_cache import ModelCacheStore
    from barbaros.workers import ListModelWorker

logger = logging.getLogger(__name__)

#: How long ``stop_fetching_models`` may block the GUI waiting for a cancelled
#: fetch (BAR-23).  Cancellation is cooperative, so a responsive worker stops in
#: milliseconds; the budget only bounds the pathological case of a worker that
#: cannot be interrupted.
STOP_WAIT_MS = 1000

#: Total budget for ``shutdown()`` across all fetch workers (BAR-23): the app
#: must be able to quit even when an endpoint never answers.  Set below the
#: 2 s NFR so the bounded shutdown stays under it even with Qt overhead.
SHUTDOWN_BUDGET_MS = 1500


@dataclass_json
@dataclass
class ProviderMeta:
    name: str
    provider_type: LLMProvider
    api_base: str | None = None

    def __post_init__(self):
        self.api_key_manager = KeySecurityManager(self.name)


@dataclass
class ProviderClient:
    meta: ProviderMeta
    models: Sequence[Model]

    def client(self):
        """
        AnyLLM client.

        httpx.AsyncClient inside ProviderClient.client (AnyLLM) maintains state (connection pool)
        between calls in the same thread, while the event loop is removed when asyncio.run() exits.
        When attempting to reuse the client from another worker instance (Qt thread),
        it accesses an already closed event loop. Therefore, we recreate the client here
        instead of reusing ProviderClient.client.
        """
        return AnyLLM.create(self.meta.provider_type, self.meta.api_key_manager.get(), self.meta.api_base)


class CachePolicy(Enum):
    """Whether ``ModelManager.add()`` should hydrate a provider from the disk cache.

    ``IGNORE`` is the safe default: runtime additions (dialog, ``update``) start
    with an empty model list and do not touch the cache.  ``RESTORE`` is used by
    the composition root on startup to bring back the previously fetched lists.
    """

    IGNORE = "ignore"
    RESTORE = "restore"


def _short_repr(value: object, limit: int = 64) -> str:
    """Log-safe repr for external strings (BAR-17: no raw CR/LF into logs)."""
    text = repr(value)
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


class _FetchResultsDispatcher(QObject):
    """One fetch worker's result delivery to the thread owning the ``ModelManager``.

    The manager's mutable state (the ``RLock``, the model cache store) belongs
    to the thread that created it; a worker thread must only emit the result
    signal, never call back into the manager.  The queued connection moves both
    result handling and the cache write to the manager's thread, and a worker
    that lingers past ``stop_fetching_models`` (cooperative cancellation can be
    ignored, BAR-23) cannot touch state the GUI is changing.

    The dispatcher is created per fetch and remembers its worker: a result that
    arrives after that worker was stopped or replaced (a queued delivery posted
    before ``cancel()``) is dropped instead of overwriting the provider's models
    with a stale list.  The worker is remembered by Python identity, which stays
    valid even when Qt has already deleted the worker's C++ object; the manager
    keeps each dispatcher referenced until its thread is destroyed.
    """

    def __init__(self, manager: ModelManager, worker: ListModelWorker) -> None:
        super().__init__()
        self._manager = manager
        self._worker = worker

    @Slot(ProviderMeta, str)
    def on_finished(self, provider: ProviderMeta, marshaled_models: str) -> None:
        self._manager._apply_worker_result(self._worker, provider, marshaled_models)

    @Slot(ProviderMeta, str)
    def on_error(self, provider: ProviderMeta, error_msg: str) -> None:
        self._manager._apply_worker_error(self._worker, provider, error_msg)


class ModelManager(dict):
    """
    Manager for handling LLM providers and their models.

    Inherits from dict, where keys are provider names (str),
    and values are ProviderClient instances.

    ``cache`` is an optional model-list store (see ``barbaros.model_cache``).
    The manager never resolves a path or parses JSON itself: it only knows the
    ``load``/``save`` port.  Construction performs no I/O; cache writes happen
    on ``set_models``/``remove``, cache reads only on ``add(cache_policy=RESTORE)``.
    """

    added = Signal(ProviderMeta)
    removed = Signal(str)
    loaded_list_models = Signal()
    worker_started = Signal()
    worker_finished = Signal()
    error = Signal(str)

    _fetching_models_workers: dict[str, tuple[ListModelWorker, QThread]]    # Key: provider name

    def __init__(self, cache: ModelCacheStore | None = None):
        super().__init__()
        self._cache = cache
        self._lock = threading.RLock()
        self._fetching_models_workers = {}
        # Result dispatchers of the current fetch per provider, kept referenced
        # until the worker's thread is destroyed (BAR-23).
        self._fetch_result_dispatchers: dict[str, tuple[QThread, _FetchResultsDispatcher]] = {}
        # Workers whose stop budget expired; referenced until their thread is
        # destroyed so a running QThread is never garbage-collected (BAR-23).
        self._retiring_workers: list[tuple[ListModelWorker, QThread]] = []

    @staticmethod
    def default_providers() -> list[ProviderMeta]:
        """Factory for the provider list used when the config has none."""
        return [ProviderMeta("ollama", LLMProvider.OLLAMA)]

    @property
    def fetching_models_active_workers(self) -> list[str]:
        return [k for k, (w, t) in self._fetching_models_workers.items() if not t.isFinished()]

    def add(self, provider: ProviderMeta, *, cache_policy: CachePolicy = CachePolicy.IGNORE):
        models: Sequence[Model] = []
        if cache_policy is CachePolicy.RESTORE and self._cache is not None:
            # Read outside the lock: disk I/O must not block mutations, and the
            # store is safe for concurrent load/save.
            try:
                cached = self._cache.load().get(provider.name, [])
            except Exception:
                # The store contract says load() never raises; keep startup
                # fail-safe even if a substitute store breaks that contract.
                logger.warning("ModelManager: loading model cache failed", exc_info=True)
                cached = []
            models = self._parse_models(cached, provider.name)

        with self._lock:
            client = ProviderClient(meta=provider, models=models)
            super().__setitem__(provider.name, client)

        self.added.emit(client)

    def remove(self, name: str):
        self.stop_fetching_models(name)
        with self._lock:
            super().pop(name, None)
            self._persist()
        self.removed.emit(name)

    def update(self, provider: ProviderMeta):
        self.remove(provider.name)
        self.add(provider)

    def __getitem__(self, item: ProviderMeta | str) -> ProviderClient:
        name = item if isinstance(item, str) else item.name
        return super().__getitem__(name)

    def to_list(self) -> list[dict]:
        metas = [v.meta for v in self.values()]
        return ProviderMeta.schema().dump(metas, many=True)

    def to_models_dict(self) -> dict[str, list[dict]]:
        """Snapshot in the cache allowlist shape (``provider_models`` layout).

        ``Model.to_dict()`` mirrors any-llm's model, which may grow fields the
        app neither needs nor validates; the cache contract is the same
        allowlist the fetched lists are normalized to.
        """
        with self._lock:
            return {
                name: model_entries(client.models)
                for name, client in self.items()
            }

    def shutdown(self):
        """Cancel all fetch workers, blocking the GUI for a bounded time (BAR-23).

        The total wait is capped by ``SHUTDOWN_BUDGET_MS``: quitting must work
        even when an endpoint never answers.  Idempotent.
        """
        names = list(self._fetching_models_workers)
        if names:
            logger.info("ModelManager shutdown: stopping %d fetch worker(s)", len(names))
            self._stop_workers(names, SHUTDOWN_BUDGET_MS)

        # Retired workers are not awaited again (their budget was already spent);
        # report them so a stuck provider is visible in the log (BAR-23).
        if self._retiring_workers:
            logger.warning(
                "ModelManager shutdown: %d fetch worker(s) were already left running past their stop budget",
                len(self._retiring_workers),
            )

    def _stop_workers(self, names: Sequence[str], budget_ms: int) -> None:
        """Stop several fetch workers under one shared deadline (BAR-23)."""
        deadline = time.monotonic() + budget_ms / 1000
        for name in names:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            self.stop_fetching_models(name, wait_ms=remaining_ms)

    def stop_fetching_models(self, provider_name: str, *, wait_ms: int | None = None):
        """Cancel a provider's model fetch, waiting at most ``wait_ms`` (BAR-23).

        Cancellation is cooperative (``ListModelWorker.cancel``), never
        ``QThread.terminate()``: Qt discourages termination and a terminated
        thread does not release the Python locks it holds.  The GUI therefore
        blocks for at most the budget; a worker that ignores cancellation is
        logged and left to finish on its own, because hanging the GUI (or the
        application exit) on an unresponsive endpoint is the defect this fix
        removes.
        """
        entry = self._fetching_models_workers.pop(provider_name, None)
        if entry is None:
            return

        worker, thread = entry
        budget_ms = STOP_WAIT_MS if wait_ms is None else wait_ms

        logger.debug("ModelManager: stopping the fetch worker for %s", _short_repr(provider_name))
        worker.cancel()

        if not thread.isRunning():
            return

        if budget_ms <= 0:
            logger.warning(
                "ModelManager: no shutdown budget left to wait for the %s fetch worker",
                _short_repr(provider_name),
            )
            self._retire_fetch_worker(worker, thread)
            return

        if not thread.wait(budget_ms):
            logger.warning(
                "ModelManager: %s fetch worker did not stop within %d ms; not blocking the GUI",
                _short_repr(provider_name),
                budget_ms,
            )
            self._retire_fetch_worker(worker, thread)

    def _retire_fetch_worker(self, worker: ListModelWorker, thread: QThread) -> None:
        """Keep an unresponsive worker referenced until its thread dies.

        Destroying a ``QThread`` that is still running aborts the process, so a
        worker that ignored the stop budget must not be garbage-collected while
        its thread finishes in the background (BAR-23).
        """
        self._retiring_workers.append((worker, thread))

    def start_fetching_models(self, provider: ProviderClient | str | None = None):
        if isinstance(provider, str):
            provider = self[provider]

        providers = [provider]

        if provider is None:
            providers = self.values()

        # A reload of several providers is also a batch stop of their previous
        # fetches: one shared deadline keeps the GUI block bounded by
        # ``SHUTDOWN_BUDGET_MS`` instead of N times ``STOP_WAIT_MS`` (BAR-23).
        previous = [p.meta.name for p in providers if p.meta.name in self._fetching_models_workers]
        if len(previous) > 1:
            self._stop_workers(previous, SHUTDOWN_BUDGET_MS)

        for p in providers:
            self._start_fetching_models(p)

    def _start_fetching_models(self, provider: ProviderClient):
        from barbaros.workers import ListModelWorker

        self.stop_fetching_models(provider.meta.name)

        thread = QThread()
        thread.setServiceLevel(QThread.QualityOfService.Eco)

        thread.finished.connect(thread.deleteLater)

        worker = ListModelWorker(provider)
        worker.moveToThread(thread)
        worker.connect_terminate(thread)
        thread.started.connect(self._on_started_thread)
        thread.started.connect(worker.run)

        dispatcher = _FetchResultsDispatcher(self, worker)
        worker.finished.connect(dispatcher.on_finished, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(dispatcher.on_error, Qt.ConnectionType.QueuedConnection)
        thread.destroyed.connect(partial(self._remove_worker, provider.meta.name, thread))

        self._fetching_models_workers[provider.meta.name] = (worker, thread)
        self._fetch_result_dispatchers[provider.meta.name] = (thread, dispatcher)

        thread.start()
        thread.setPriority(QThread.Priority.LowPriority)

    def _remove_worker(self, provider_name: str, thread: QThread):
        """Forget a destroyed worker, but only if it is still the tracked one.

        A worker whose thread outlived the stop budget (BAR-23) may be destroyed
        after the same provider already started a newer fetch; it must not evict
        that newer worker from the tracking map.
        """
        entry = self._fetching_models_workers.get(provider_name)
        if entry is not None and entry[1] is thread:
            self._fetching_models_workers.pop(provider_name)
        dispatcher_entry = self._fetch_result_dispatchers.get(provider_name)
        if dispatcher_entry is not None and dispatcher_entry[0] is thread:
            self._fetch_result_dispatchers.pop(provider_name)
        self._retiring_workers = [pair for pair in self._retiring_workers if pair[1] is not thread]
        self.worker_finished.emit()

    def _on_started_thread(self, *args, **kwargs):
        self.worker_started.emit()

    def _on_fetching_error(self, provider: ProviderMeta, error_msg: str):
        self.error.emit(f"Error on fetching models for `{provider.name}` ({provider.provider_type}): {error_msg}")

    def _apply_worker_result(
        self,
        worker: ListModelWorker | None,
        provider: ProviderMeta,
        marshaled_models: str,
    ) -> None:
        """Apply a fetched list only if it belongs to the provider's tracked worker.

        A result can be queued before the fetch is stopped (Reload, remove a
        provider, quit); applying it then would overwrite the newer list with
        stale models or resurrect a provider the user removed (BAR-23).
        """
        entry = self._fetching_models_workers.get(provider.name)
        if entry is None or entry[0] is not worker:
            logger.debug(
                "ModelManager: dropping the result of a stopped fetch for %s",
                _short_repr(provider.name),
            )
            return

        self._on_fetching_finished(provider, marshaled_models)

    def _apply_worker_error(
        self,
        worker: ListModelWorker | None,
        provider: ProviderMeta,
        error_msg: str,
    ) -> None:
        """Report a fetch failure only for the provider's tracked worker (BAR-23).

        Symmetric to ``_apply_worker_result``: an abandoned or superseded worker
        that fails later must not raise a dialog for a fetch the user already
        stopped (cancellation itself never emits ``error``).
        """
        entry = self._fetching_models_workers.get(provider.name)
        if entry is None or entry[0] is not worker:
            logger.debug(
                "ModelManager: dropping the error of a stopped fetch for %s",
                _short_repr(provider.name),
            )
            return

        self._on_fetching_error(provider, error_msg)

    def _on_fetching_finished(self, provider: ProviderMeta, marshaled_models: str):
        try:
            entries = json.loads(marshaled_models)
        except (TypeError, ValueError):
            entries = None

        if not isinstance(entries, list):
            # The hand-off comes from our own worker; a malformed payload is a
            # programming error, not user input.  Never let it escape a Qt slot:
            # the exception would abort result handling with no visible cause.
            logger.warning(
                "ModelManager: malformed model list payload for provider %s",
                _short_repr(provider.name),
            )
            self._on_fetching_error(provider, "invalid model list payload")
            return

        models = self._parse_fetched_models(entries, provider.name)
        self.set_models(provider, models)

    def set_models(self, provider: ProviderMeta | str, models: Sequence[Model]):
        name = provider if isinstance(provider, str) else provider.name
        with self._lock:
            client = super().get(name)
            if client is None:
                # A fetch may finish after the provider was removed/replaced;
                # its result must not resurrect the provider or crash the slot.
                logger.debug(
                    "ModelManager: ignoring models for removed provider %s",
                    _short_repr(name),
                )
                return
            client.models = models
            # Full snapshot under the lock: the last save always reflects the
            # newest in-memory state, even with concurrent callers.
            self._persist()
        self.loaded_list_models.emit()

    @staticmethod
    def _parse_models(cached: Sequence[dict], provider_name: str) -> list[Model]:
        """Restore cached entries; strict typing keeps the disk format authoritative.

        A lenient ``Model`` coerces ``created`` from bool/float/numeric strings,
        which would let malformed cached data resurface and be written back.
        """
        models, skipped = ModelManager._validate_models(cached)
        if skipped:
            logger.debug(
                "ModelManager: skipped %d invalid cached model entries for provider %s",
                skipped,
                _short_repr(provider_name),
            )
        return models

    @staticmethod
    def _parse_fetched_models(entries: Sequence[object], provider_name: str) -> list[Model]:
        """Validate the worker→manager hand-off.

        One unusable entry must not drop the whole fetched list (or raise into a
        Qt slot): keep the valid models, log the rest.
        """
        models, skipped = ModelManager._validate_models(entries)
        if skipped:
            logger.warning(
                "ModelManager: skipped %d invalid fetched model entries for provider %s",
                skipped,
                _short_repr(provider_name),
            )
        return models

    @staticmethod
    def _validate_models(entries: Sequence[object]) -> tuple[list[Model], int]:
        """Validate entries strictly, counting (never raising on) invalid ones."""
        models: list[Model] = []
        skipped = 0
        for entry in entries:
            try:
                models.append(Model.model_validate(entry, strict=True))
            except Exception:
                skipped += 1
        return models, skipped

    def _persist(self) -> None:
        """Write a full snapshot; called under ``self._lock``.

        A store failure must not break the app: the in-memory state is already
        updated, the cache is regenerable and the next successful save writes a
        full snapshot.  The real store is fail-safe itself; this guards any
        store implementation (and contract regressions) from escaping.
        """
        if self._cache is None:
            return
        try:
            self._cache.save(self.to_models_dict())
        except Exception:
            logger.warning("ModelManager: saving model cache failed", exc_info=True)
