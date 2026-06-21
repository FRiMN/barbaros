from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from any_llm import AnyLLM, LLMProvider
from any_llm.types.model import Model
from any_llm.exceptions import AnyLLMError
from psygnal import Signal
from PySide6.QtCore import QThread

from barbaros.security import KeySecurityManager

if TYPE_CHECKING:
    from barbaros.workers import ListModelWorker


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


default_providers = [
    ProviderMeta("ollama", LLMProvider.OLLAMA)
]


class ModelManager(dict):
    """
    Manager for handling LLM providers and their models.

    Inherits from dict, where keys are provider names (str),
    and values are ProviderClient instances.
    """

    added = Signal(ProviderMeta)
    removed = Signal(str)
    loaded_list_models = Signal()
    worker_started = Signal()
    worker_finished = Signal()
    error = Signal(str)

    _fetching_models_workers: dict[str, tuple[ListModelWorker, QThread]]    # Key: provider name

    def __init__(self):
        super().__init__()
        self._fetching_models_workers = {}

    @property
    def fetching_models_active_workers(self) -> list[str]:
        return [k for k, (w, t) in self._fetching_models_workers.items() if not t.isFinished()]

    def add(self, provider: ProviderMeta):
        v = ProviderClient(meta=provider, models=[])
        super().__setitem__(provider.name, v)

        print(f"start fetch models list for {provider.name}")
        self._start_fetching_models(v)

        self.added.emit(v)

    def remove(self, name: str):
        super().pop(name, None)
        self.removed.emit(name)

    def update(self, provider: ProviderMeta):
        self.remove(provider.name)
        self.add(provider)

    def __getitem__(self, item: ProviderMeta | str) -> ProviderClient:
        name = item if isinstance(item, str) else item.name
        return super().__getitem__(name)

    def to_list(self) -> list[ProviderMeta]:
        return [v.meta for v in self.values()]

    def to_models_dict(self) -> dict[str, list[dict]]:
        d = {}
        for name, client in self.items():
            models = [m.to_dict() for m in client.models]
            d[name] = models
        return d

    def shutdown(self):
        """Shutdown all threads and cleanup."""
        print("ModelManager shutdown: cleaning up threads...")
        # List on iterator, because changing dict
        for name in list(self._fetching_models_workers.keys()):
            self.stop_fetching_models(name)

    def stop_fetching_models(self, provider_name: str):
        if provider_name not in self._fetching_models_workers:
            return

        worker, thread = self._fetching_models_workers.pop(provider_name)
        worker: ListModelWorker
        thread: QThread

        try:
            if thread.isRunning():
                thread.terminate()
                thread.wait(3000)

            worker.deleteLater()
            thread.deleteLater()
        except RuntimeError:
            pass

    def _start_fetching_models(self, provider: ProviderClient):
        from barbaros.workers import ListModelWorker

        self.stop_fetching_models(provider.meta.name)

        thread = QThread()
        thread.setServiceLevel(QThread.QualityOfService.Eco)

        thread.finished.connect(thread.deleteLater)

        worker = ListModelWorker(provider)
        worker.moveToThread(thread)
        worker.connect_terminate(thread)
        thread.started.connect(worker.run)

        worker.finished.connect(self._on_fetching_finished)
        worker.error.connect(self._on_fetching_error)
        thread.destroyed.connect(partial(self._remove_worker, provider.meta.name))

        thread.started.connect(self.worker_started)
        worker.finished.connect(self.worker_finished)

        self._fetching_models_workers[provider.meta.name] = (worker, thread)

        thread.start()
        thread.setPriority(QThread.Priority.LowPriority)

    def _remove_worker(self, provider_name: str):
        print(f"remove worker {provider_name}")
        if provider_name in self._fetching_models_workers:
            self._fetching_models_workers.pop(provider_name)

    def _on_fetching_error(self, provider: ProviderMeta, error_msg: str):
        self.error.emit(f"Error on fetching models for `{provider.name}` ({provider.provider_type}): {error_msg}")

    def _on_fetching_finished(self, provider: ProviderMeta, marshaled_models: str):
        models = json.loads(marshaled_models)
        models = [Model.model_validate(m) for m in models]
        self.set_models(provider, models)

    def set_models(self, provider: ProviderMeta | str, models: Sequence[Model]):
        client: ProviderClient = self[provider]
        client.models = models
        self.loaded_list_models.emit()
