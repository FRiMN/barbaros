from dataclasses import dataclass
from importlib.resources import path, files, open_text
from enum import Enum

from PySide6.QtGui import QPixmap


PACKAGE = 'barbaros.resources'
ICONS_LOC = f"{PACKAGE}.icons"


class Resource(Enum):
    icon_app = QPixmap(files(ICONS_LOC).joinpath('icon3.png'))
    translation_agent_system_prompt = open_text(PACKAGE, 'translation_agent_prompt.md').read()
