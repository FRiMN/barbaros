from __future__ import annotations
import typing
from PySide6.QtCore import QCoreApplication, QLocale, QTranslator

DEFAULT_LANGUAGE = "en"

_QM_PREFIX = "barbaros_"


def _(context: str, text: str) -> str:
    """Translate ``text`` in ``context`` (for non-QObject code).

    Use only where ``self.tr()`` is not available.
    """
    return QCoreApplication.translate(context, text)


def _qm_dir() -> typing.Any:
    from importlib.resources import files

    return files("barbaros.i18n")


def available_languages() -> list[str]:
    """Return language codes that have a compiled ``.qm`` file."""
    try:
        qm_dir = _qm_dir()
    except ModuleNotFoundError:
        return [DEFAULT_LANGUAGE]

    langs: set[str] = set()
    for entry in qm_dir.iterdir():
        name = entry.name
        if name.startswith(_QM_PREFIX) and name.endswith(".qm"):
            langs.add(name[len(_QM_PREFIX):-3])
    return sorted(langs) or [DEFAULT_LANGUAGE]


def language_display_name(lang: str) -> str:
    """Return a human-readable name for ``lang`` (English name)."""
    locale = QLocale(lang)
    return locale.languageToString(locale.language())


def resolve_language(setting: str | None) -> str:
    """Resolve a stored language setting to a concrete language code.

    An empty/``None`` setting falls back to the system locale language and
    ultimately to :data:`DEFAULT_LANGUAGE`.
    """
    if setting:
        return setting

    system = QLocale.system().name()  # e.g. 'ru_RU'
    lang = system.split("_")[0]
    return lang or DEFAULT_LANGUAGE


def load_translator(lang: str) -> QTranslator | None:
    """Load the ``.qm`` for ``lang`` and return a :class:`QTranslator`."""
    if not lang or lang == DEFAULT_LANGUAGE:
        return None

    qm_name = f"{_QM_PREFIX}{lang}.qm"
    try:
        qm_path = str(_qm_dir().joinpath(qm_name))
    except ModuleNotFoundError:
        return None

    translator = QTranslator()
    if translator.load(qm_path):
        return translator

    return None
