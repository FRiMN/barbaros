import typing
import re

from PySide6.QtCore import QSettings


class SettingsProxy:
    """Proxy for QSettings with a prefix"""
    def __init__(self, settings: QSettings, prefix: str):
        self.settings = settings
        self.prefix = prefix

    def _prefixed_key(self, key: str) -> str:
        return f"{self.prefix}/{key}"

    def value(self, key: str, default=None) -> typing.Any:
        return self.settings.value(self._prefixed_key(key), default)

    def setValue(self, key: str, value):
        self.settings.setValue(self._prefixed_key(key), value)

    def contains(self, key: str) -> bool:
        return self.settings.contains(self._prefixed_key(key))

    def remove(self, key: str):
        self.settings.remove(self._prefixed_key(key))

    def allKeys(self) -> list[str]:
        self.settings.beginGroup(self.prefix)
        keys = self.settings.allKeys()
        self.settings.endGroup()
        return keys

    def childKeys(self) -> list[str]:
        self.settings.beginGroup(self.prefix)
        keys = self.settings.childKeys()
        self.settings.endGroup()
        return keys

    def childGroups(self) -> list[str]:
        self.settings.beginGroup(self.prefix)
        groups = self.settings.childGroups()
        self.settings.endGroup()
        return groups

    def __getattr__(self, name):
        # Delegate any other methods directly to the underlying QSettings object
        return getattr(self.settings, name)


def is_valid_url(url: str) -> bool:
    if not url:
        return False

    url_pattern = re.compile(
        r'^https?://'                                        # Protocol: http or https
        r'(?:'                                                      # Domain labels
        r'(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}'    # TLD
        r'|localhost'                                               # Localhost
        r'|(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)'  # IPv4 address
        r')'
        r'(?::\d+)?'                                                # Port
        r'(?:/(?:\S*)?)?$',                                         # Path and query
        re.IGNORECASE
    )
    return bool(url_pattern.match(url))


def truncate_key(key: str) -> str:
    """Truncate API key to show only last 15% of key, but 4 chars max."""
    key_len = len(key)
    if 4 <= key_len * 0.15:
        return f"****{key[-4:]}"
    truncate_len = max(1, int(key_len * 0.15))
    return f"****{key[-truncate_len:]}"


TARGET_LANGUAGES = [
    "ru",
    "en",
    "fr",
    "de",
    "es",
    "it",
    "pt",
    "ja",
    "ko",
    "zh",
    "ar",
    "hi",
    "ua",
]
