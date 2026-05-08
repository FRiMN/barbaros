from collections.abc import Sequence
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from any_llm import AnyLLM, LLMProvider
from any_llm.types.model import Model
from any_llm.exceptions import AnyLLMError

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
    def add(self, provider: ProviderMeta, timeout: int = 3, error_callback=None):
        error_callback = error_callback or print

        try:
            client = AnyLLM.create(provider.provider_type, provider.api_key_manager.get(), provider.api_base)
        except AnyLLMError as e:
            msg = f"Error for provider {provider.name} ({provider.provider_type}): {e}"
            error_callback(msg)
            return

        try:
            with ThreadPoolExecutor() as executor:
                future = executor.submit(client.list_models)
                models = future.result(timeout=timeout)
        except TimeoutError:
            msg = f"Timeout adding provider {provider.name} ({provider.provider_type}): exceeded {timeout}s"
            error_callback(msg)
            models = []
        except (BaseException, AnyLLMError) as e:
            msg = f"Error for provider {provider.name} ({provider.provider_type}): {e}"
            error_callback(msg)
            models = []

        v = ProviderClient(meta=provider, client=client, models=models)
        super().__setitem__(provider.name, v)

    def remove(self, name: str):
        super().pop(name, None)

    def update(self, provider: ProviderMeta, timeout: int = 3, error_callback=None):
        self.remove(provider.name)
        self.add(provider, timeout, error_callback)

    def __getitem__(self, item: ProviderMeta | str) -> ProviderClient:
        name = item if isinstance(item, str) else item.name
        return super().__getitem__(name)

    def to_list(self) -> list[ProviderMeta]:
        return [v.meta for v in self.values()]
