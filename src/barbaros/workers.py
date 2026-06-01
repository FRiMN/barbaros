import json
from collections.abc import Sequence

from PySide6.QtCore import QObject, Signal, Slot, QThread
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
        # System prompt: "Extract the text in the image."
        try:
            ocr_text = ocr_image(self.image_bytes, self.model.model)
            self.finished.emit(ocr_text)
        except Exception as e:
            self.error.emit(str(e))


class ListModelWorker(QObject):
    """Fetching models for provider"""
    finished = Signal(ProviderMeta, str)
    error = Signal(ProviderMeta, str)

    marshaling_fields = {"id", "created", "object", "owned_by"}

    def __init__(self, provider: ProviderClient):
        super().__init__()
        self.provider = provider

    @Slot()
    def run(self):
        print(f"Fetching models for '{self.provider.meta.name}' ({self.provider.meta.provider_type})")
        try:
            models: Sequence[Model] = self.provider.client.list_models()

            # See: https://github.com/mozilla-ai/any-llm/issues/1083
            for model in models:
                if model.owned_by is None:
                    model.owned_by = ""
                model.object = "model"

            marshaled_models = json.dumps([
                m.model_dump(include=self.marshaling_fields)
                for m in models
            ])
            print(f"emit finished {self.provider.meta.name=} (found {len(models)} models)")
            self.finished.emit(self.provider.meta, marshaled_models)
        except Exception as e:
            print(f"emit error {self.provider.meta.name=}")
            self.error.emit(self.provider.meta, str(e))

    def connect_terminate(self, thread: QThread):
        for signal in (self.finished, self.error):
            signal.connect(self.deleteLater)
            signal.connect(thread.quit)
