import sys

import pytest
from PySide6.QtCore import QCoreApplication, QTranslator

from barbaros.i18n import (
    available_languages,
    language_display_name,
    load_translator,
    resolve_language,
)


@pytest.fixture(scope="module")
def app():
    application = QCoreApplication.instance() or QCoreApplication(sys.argv)
    yield application


def test_available_languages_includes_russian():
    assert "ru" in available_languages()


def test_resolve_language_explicit():
    assert resolve_language("ru") == "ru"
    assert resolve_language("de") == "de"


def test_resolve_language_empty_falls_back_to_system():
    # Empty/None falls back to a 2-letter system language code (never empty).
    assert len(resolve_language("")) == 2
    assert len(resolve_language(None)) == 2


def test_language_display_name():
    name = language_display_name("ru")
    assert isinstance(name, str)
    assert name


def test_load_translator_russian(app):
    translator = load_translator("ru")
    assert translator is not None
    assert app.installTranslator(translator)
    try:
        assert (
            QCoreApplication.translate("MainWindow", "Clear widgets")
            == "Очистить виджеты"
        )
        assert (
            QCoreApplication.translate("TextFeature", "Translate") == "Перевести"
        )
        # Placeholders must survive translation.
        assert (
            QCoreApplication.translate("TextFeature", "Eval: %1s; %2 tkn/s")
            == "Оценка: %1 с; %2 ток/с"
        )
    finally:
        app.removeTranslator(translator)


def test_load_translator_default_is_none():
    # English is the source language, so no translator is needed.
    assert load_translator("en") is None
    assert load_translator("") is None
