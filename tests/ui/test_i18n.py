import sys
import xml.etree.ElementTree as ET
from pathlib import Path

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


def _ts_files() -> tuple[list[Path], Path]:
    ts_dir = Path(__file__).resolve().parents[2] / "src" / "barbaros" / "i18n"
    return sorted(ts_dir.glob("*.ts")), ts_dir


def _qm_files() -> tuple[list[Path], Path]:
    qm_dir = Path(__file__).resolve().parents[2] / "src" / "barbaros" / "i18n"
    return sorted(qm_dir.glob("*.qm")), qm_dir


def test_available_languages_includes_all_ts():
    ts_files, ts_dir = _ts_files()
    assert len(available_languages()) == len(ts_files)


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
    """
    Перед тестированием проверь, что ts скомпилированы в qm
    """
    translator = load_translator("ru")
    assert translator is not None
    assert app.installTranslator(translator)
    try:
        assert (
            QCoreApplication.translate("MainWindow", "Clear widgets") == "Очистить виджеты"
        )
        assert (
            QCoreApplication.translate("TextFeature", "Translate") == "Перевести"
        )
    finally:
        app.removeTranslator(translator)


def test_load_translator_default_is_none():
    # English is the source language, so no translator is needed.
    assert load_translator("en") is None
    assert load_translator("") is None


def test_ts_files_have_locations_and_no_vanished():
    ts_files, ts_dir = _ts_files()
    assert ts_files, f"no .ts files found in {ts_dir}"

    for ts in ts_files:
        root = ET.parse(ts).getroot()
        for message in root.iter("message"):
            source = message.findtext("source")
            location = message.find("location")
            translation = message.find("translation")

            assert location is not None, (
                f"{ts.name}: message {source!r} has no <location>"
            )
            assert translation is not None, (
                f"{ts.name}: message {source!r} has no <translation>"
            )
            assert translation.get("type") != "vanished", (
                f"{ts.name}: message {source!r} is vanished"
            )


def test_compiled_translations_are_non_trivial():
    qm_files, qm_dir = _qm_files()
    assert qm_files, f"no .qm files found in {qm_dir}"

    for qm in qm_files:
        size = qm.stat().st_size
        assert size > 100, (
            f"{qm.name} is only {size} bytes; "
            f"likely compiled from an empty/vanished .ts"
        )
