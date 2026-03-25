from PySide6.QtCore import QObject, Signal, Slot
from ollama import GenerateResponse
from .translator import translate_text, ocr_image


class TranslationWorker(QObject):
    finished = Signal(GenerateResponse)
    error = Signal(str)

    def __init__(self, text_to_translate: str, target_language: str, model: str):
        super().__init__()
        self.text_to_translate = text_to_translate
        self.target_language = target_language
        self.model = model

    @Slot()
    def run(self):
        """Run in thread."""
        print("in thread")
        resp: GenerateResponse = translate_text(
            self.text_to_translate, self.target_language, self.model
        )
        print(f"{resp=}")
        self.finished.emit(resp)


class OCRWorker(QObject):
    finished = Signal(str, str)
    error = Signal(str)

    def __init__(self, image_bytes: bytes, target_language: str, model: str):
        super().__init__()
        self.image_bytes = image_bytes
        self.target_language = target_language
        self.model = model

    @Slot()
    def run(self):
        print("OCR worker started")
        ocr_text = ocr_image(self.image_bytes, self.model)
        print(f"{ocr_text=}")
        translation_resp = translate_text(ocr_text, self.target_language, self.model)
        print(f"{translation_resp=}")
        self.finished.emit(ocr_text, translation_resp.response)
