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
        try:
            resp: GenerateResponse = translate_text(
                self.text_to_translate, self.target_language, self.model
            )
            print(f"{resp=}")
            self.finished.emit(resp)
        except Exception as e:
            self.error.emit(str(e))


class OCRWorker(QObject):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, image_bytes: bytes, model: str):
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
