from collections.abc import Sequence
from dataclasses import dataclass

from any_llm import AnyLLM, LLMProvider
from any_llm.types.model import Model


@dataclass
class ProviderMeta:
    name: str
    provider_type: LLMProvider
    api_key: str | None = None
    api_base: str | None = None


@dataclass
class ProviderClient:
    meta: ProviderMeta
    client: AnyLLM
    models: Sequence[Model]


default_providers = [
    ProviderMeta("ollama", LLMProvider.OLLAMA)
]


class ModelManager(dict):
    def add(self, provider: ProviderMeta):
        client = AnyLLM.create(provider.provider_type, provider.api_key, provider.api_base)
        try:
            models = client.list_models()
        except ConnectionError as e:
            # TDOD: show error in GUI
            print(e)
            models = []
        v = ProviderClient(meta=provider, client=client, models=models)
        super().__setitem__(provider.name, v)

    def __getitem__(self, item: ProviderMeta | str) -> ProviderClient:
        name = item if isinstance(item, str) else item.name
        return super().__getitem__(name)
