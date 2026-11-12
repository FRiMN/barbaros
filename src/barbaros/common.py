import json
import logging
import re
import typing

from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)


def read_setting(settings: QSettings, key: str, default=None):
    """Read a QSettings value without crashing on legacy pickled data (BAR-01).

    PySide6 6.12 raises ``RuntimeError`` instead of unpickling a
    ``PySide::PyObjectWrapper`` value.  The rejection flag is checked per INI
    *section*: the first read that parses a section containing such a value
    fails (and clears the flag), so an immediate retry of that key returns the
    value normally.  A retry returning ``None`` means the key itself holds the
    rejected value - then ``default`` is used.  Such values are removed before
    QSettings is created (``settings_sanitize``); this guard covers the cases
    where that was not possible (read-only config directory, symlinked file,
    ...).
    """
    try:
        return settings.value(key, default)
    except RuntimeError:
        logger.warning("Settings: legacy value in the section of %r, retrying", key)

    try:
        value = settings.value(key)
    except RuntimeError:
        logger.warning("Settings: cannot read %r, using the default", key)
        return default

    if value is None:
        # The flag was cleared by the retry, so a still-missing value means Qt
        # rejected this very key (or the key is absent): use the default.
        logger.warning("Settings: %r is not readable, using the default", key)
        return default
    return value


class SettingsProxy:
    """Proxy for QSettings with a prefix"""
    def __init__(self, settings: QSettings, prefix: str):
        self.settings = settings
        self.prefix = prefix

    def _prefixed_key(self, key: str) -> str:
        return f"{self.prefix}/{key}"

    def value(self, key: str, default=None) -> typing.Any:
        return read_setting(self.settings, self._prefixed_key(key), default)

    def valueFromJson(self, key: str, default=None):
        v = self.value(key)
        if v is None:
            return default
        try:
            return json.loads(v)
        except (TypeError, ValueError, RecursionError) as exc:
            # RecursionError (deeply nested input) is a RuntimeError subclass,
            # so it must be listed explicitly: a hostile config value must not
            # abort startup.
            logger.warning(
                "Settings: %r is not valid JSON (%s), using the default",
                self._prefixed_key(key),
                exc.__class__.__name__,
            )
            return default

    def setValue(self, key: str, value):
        self.settings.setValue(self._prefixed_key(key), value)

    def setValueAsJson(self, key: str, value):
        v = json.dumps(value)
        self.setValue(key, v)

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
    if key_len * 0.15 >= 4:
        return f"****{key[-4:]}"
    truncate_len = max(1, int(key_len * 0.15))
    return f"****{key[-truncate_len:]}"


def url_to_html_links(text: str) -> str:
    import re

    url_pattern = re.compile(r'(https?://[^\s]+)')
    return url_pattern.sub(r'<a href="\1">\1</a>', text)


TARGET_LANGUAGES = ['ar', 'de', 'en', 'es', 'fr', 'hi', 'it', 'ja', 'ko', 'pt', 'ru', 'ua', 'zh']
