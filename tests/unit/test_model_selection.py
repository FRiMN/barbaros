"""Unit tests for the JSON form of ``ModelSelection`` used by QSettings (BAR-01)."""

from __future__ import annotations

import pytest

from barbaros.widgets.filterable_combobox import ModelSelection


def test_to_dict_has_only_string_fields():
    selection = ModelSelection(provider="ollama", model="llama3")

    assert selection.to_dict() == {"provider": "ollama", "model": "llama3"}


def test_roundtrip():
    selection = ModelSelection(provider="deepseek", model="deepseek-flash")

    assert ModelSelection.from_dict(selection.to_dict()) == selection


def test_from_dict_ignores_unknown_fields():
    restored = ModelSelection.from_dict(
        {"provider": "ollama", "model": "llama3", "api_base": "http://localhost"}
    )

    assert restored == ModelSelection(provider="ollama", model="llama3")


@pytest.mark.parametrize(
    "data",
    [
        None,
        "ollama/llama3",
        ["ollama", "llama3"],
        {},
        {"provider": "ollama"},
        {"model": "llama3"},
        {"provider": None, "model": "llama3"},
        {"provider": "ollama", "model": 3},
        {"provider": "", "model": "llama3"},
        {"provider": "ollama", "model": ""},
    ],
)
def test_malformed_data_is_rejected(data):
    assert ModelSelection.from_dict(data) is None
