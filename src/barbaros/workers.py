from PySide6.QtCore import QObject, Signal, Slot
from ollama import GenerateResponse
from .translator import translate_text


class TranslationWorker(QObject):
    finished = Signal(str)  # Worker is finished and starts to close.
    error = Signal(str)  # Worker encountered an error.

    def __init__(self, text_to_translate):
        super().__init__()
        self.text_to_translate = text_to_translate

    @Slot()
    def run(self):
        """Run in thread."""
        print("Starting translation...")
        resp: GenerateResponse = translate_text(self.text_to_translate)
        print("...done")
        self.finished.emit(resp.response)
