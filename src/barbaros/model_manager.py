from __future__ import annotations

import json
import logging
import threading
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
    """Deliver worker results to the thread that owns the ``ModelManager``.

    ``QThread.terminate()`` does not release Python locks held by the killed
    thread, so a worker must never call back into the manager: if it were
    terminated inside ``set_models``/``_persist``, the ``RLock`` (or the store's
    write lock) would stay locked forever.  This object is created in the
    manager's thread, and the queued connection moves result handling and the
    cache write there; worker threads only emit the signal.
    """

    def __init__(self, manager: ModelManager) -> None:
        super().__init__()
        self._manager = manager

    @Slot(ProviderMeta, str)
    def on_finished(self, provider: ProviderMeta, marshaled_models: str) -> None:
        self._manager._on_fetching_finished(provider, marshaled_models)


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
        self._fetch_results = _FetchResultsDispatcher(self)

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
        """Shutdown all threads and cleanup."""
        print("ModelManager shutdown: cleaning up threads...")
        # List on iterator, because changing dict
        for name in list(self._fetching_models_workers.keys()):
            self.stop_fetching_models(name)

    def stop_fetching_models(self, provider_name: str):
        if provider_name not in self._fetching_models_workers:
            return

        print(f"Stop fetching models for '{provider_name}'")

        worker, thread = self._fetching_models_workers.pop(provider_name)
        worker: ListModelWorker
        thread: QThread

        try:
            if thread.isRunning():
                print("thread is running - terminate")
                thread.terminate()
                thread.wait()
        except RuntimeError:
            pass

    def start_fetching_models(self, provider: ProviderClient | str | None = None):
        if isinstance(provider, str):
            provider = self[provider]

        providers = [provider]

        if provider is None:
            providers = self.values()

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

        worker.finished.connect(
            self._fetch_results.on_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.error.connect(self._on_fetching_error)
        thread.destroyed.connect(partial(self._remove_worker, provider.meta.name))

        self._fetching_models_workers[provider.meta.name] = (worker, thread)

        thread.start()
        thread.setPriority(QThread.Priority.LowPriority)

    def _remove_worker(self, provider_name: str):
        print(f"remove worker {provider_name}")
        if provider_name in self._fetching_models_workers:
            self._fetching_models_workers.pop(provider_name)
        self.worker_finished.emit()

    def _on_started_thread(self, *args, **kwargs):
        self.worker_started.emit()

    def _on_fetching_error(self, provider: ProviderMeta, error_msg: str):
        self.error.emit(f"Error on fetching models for `{provider.name}` ({provider.provider_type}): {error_msg}")

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
