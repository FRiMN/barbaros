import typing

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
