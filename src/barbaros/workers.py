from collections.abc import Sequence

from PySide6.QtCore import QObject, Signal, Slot
from any_llm import AnyLLM
from any_llm.types.completion import ChatCompletion
from any_llm.types.model import Model

from .model_manager import ProviderClient, ProviderMeta
from .translator import translate_text, ocr_image
from .widgets.filterable_combobox import ModelSelection


class TranslationWorker(QObject):
    finished = Signal(ChatCompletion)
    error = Signal(str)

    def __init__(self, text_to_translate: str, target_language: str, model: ModelSelection, client: AnyLLM):
        super().__init__()
        self.text_to_translate = text_to_translate
        self.target_language = target_language
        self.model = model
        self.client = client
        self.text_prompt = f"""
        Target Language: {target_language}
        Text: {text_to_translate}
        """

    @Slot()
    def run(self):
        """Run in thread."""
        from .resources_loader import Resource

        print("in thread")

        try:
            messages = [
                {"role": "system", "content": Resource.translation_agent_system_prompt.value},
                {"role": "user", "content": self.text_prompt}
            ]
            resp: ChatCompletion = self.client.completion(self.model.model, messages)

            self.finished.emit(resp)
        except Exception as e:
            self.error.emit(str(e))


class OCRWorker(QObject):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, image_bytes: bytes, model: ModelSelection):
        super().__init__()
        self.image_bytes = image_bytes
        self.model = model

    @Slot()
    def run(self):
        print("OCR worker started")
        try:
            ocr_text = ocr_image(self.image_bytes, self.model)
            self.finished.emit(ocr_text)
        except Exception as e:
            self.error.emit(str(e))


class ListModelWorker(QObject):
    """Fetching models for provider"""
    finished = Signal(ProviderMeta, Sequence[Model])
    error = Signal(ProviderMeta, str)

    def __init__(self, provider: ProviderClient):
        print(f"init worker for {provider}")
        super().__init__()
        self.provider = provider

    @Slot()
    def run(self):
        print(f"Fetching models for '{self.provider.meta.name}' ({self.provider.meta.provider_type})")
        try:
            models: Sequence[Model] = self.provider.client.list_models()
            self.finished.emit(self.provider.meta, models)
        except Exception as e:
            self.error.emit(self.provider.meta, str(e))
