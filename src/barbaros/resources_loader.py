from importlib.resources import files, open_text
from enum import Enum
from typing import List

from PySide6.QtGui import QPixmap


PACKAGE = 'barbaros.resources'
ICONS_LOC = f"{PACKAGE}.icons"


def get_ollama_models() -> List[str]:
    import ollama

    models_resp: ollama.ListResponse = ollama.list()
    models = [m.model for m in models_resp.models if m.model is not None]
    return models


class Resource(Enum):
    icon_app = QPixmap(files(ICONS_LOC).joinpath('icon3.png'))
    translation_agent_system_prompt = open_text(PACKAGE, 'translation_agent_prompt.md').read()
    dictionary_agent_system_prompt = open_text(PACKAGE, 'dictionary_agent_prompt2.md').read()
    ollama_models = get_ollama_models()
