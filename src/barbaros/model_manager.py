from collections.abc import Sequence
from dataclasses import dataclass

from any_llm import AnyLLM, LLMProvider
from any_llm.types.model import Model
from any_llm.exceptions import AnyLLMError
from psygnal import Signal
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

from barbaros.security import KeySecurityManager


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
    client: AnyLLM
    models: Sequence[Model]


default_providers = [
    ProviderMeta("ollama", LLMProvider.OLLAMA)
]


class ModelManager(dict):
    added = Signal(ProviderMeta)
    removed = Signal(str)

    def add(self, provider: ProviderMeta, timeout: int = 3, error_callback=None):
        error_callback = error_callback or print

        try:
            client = AnyLLM.create(provider.provider_type, provider.api_key_manager.get(), provider.api_base)
        except AnyLLMError as e:
            msg = f"Error for provider {provider.name} ({provider.provider_type}): {e}"
            error_callback(msg)
            return

        v = ProviderClient(meta=provider, client=client, models=[])
        super().__setitem__(provider.name, v)

        print(f"start fetch models list for {provider.name}")
        self._start_fetching_models(v)

        self.added.emit(v)

    def remove(self, name: str):
        super().pop(name, None)
        self.removed.emit(name)

    def update(self, provider: ProviderMeta, timeout: int = 3, error_callback=None):
        self.remove(provider.name)
        self.add(provider, timeout, error_callback)

    def __getitem__(self, item: ProviderMeta | str) -> ProviderClient:
        name = item if isinstance(item, str) else item.name
        return super().__getitem__(name)

    def to_list(self) -> list[ProviderMeta]:
        return [v.meta for v in self.values()]

    def _start_fetching_models(self, provider: ProviderClient):
        from barbaros.workers import ListModelWorker

        thread = QThread()
        thread.finished.connect(thread.deleteLater)

        self.worker = ListModelWorker(provider)
        print(f"{self.worker=}")
        self.worker.moveToThread(thread)

        self.worker.finished.connect(self._on_fetching_finished)
        self.worker.finished.connect(thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.error.connect(self._on_fetching_error)
        thread.started.connect(self.worker.run)

        thread.start()

    def _on_fetching_error(self, provider: ProviderMeta, error_msg: str):
        QMessageBox.critical(None, f"Error on fetching models for `{provider.name}` ({provider.provider_type})", error_msg)

    def _on_fetching_finished(self, provider: ProviderMeta, models: Sequence[Model]):
        self.set_models(provider, models)

    def set_models(self, provider: ProviderMeta, models: Sequence[Model]):
        client: ProviderClient = self[provider]
        client.models = models
