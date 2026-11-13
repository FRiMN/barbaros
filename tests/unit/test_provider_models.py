"""Unit tests for :mod:`barbaros.provider_models`.

Provider list endpoints are untrusted, and ``any_llm`` hands model items back
as ``openai.types.model.Model`` instances built leniently by the openai SDK
(``_strict_response_validation`` is off), so a required field may be ``None``.
DeepSeek's ``GET /models`` omits ``created`` entirely; the fixtures below are
built with the SDK's own ``construct_type`` so they have the exact object shape
any_llm returns, not a hand-written mock.
"""

from __future__ import annotations

import json

import pytest
from any_llm.types.model import Model
from openai._models import construct_type
from pydantic import ValidationError

from barbaros.model_cache import ModelCacheDocument
from barbaros.provider_models import (
    DEFAULT_CREATED,
    DEFAULT_OWNED_BY,
    MODEL_OBJECT,
    model_entries,
    model_entry,
)

ALLOWED_KEYS = {"id", "created", "object", "owned_by"}


def provider_model(**fields: object) -> Model:
    """One list-models item as any_llm returns it from an OpenAI-compatible endpoint."""
    return construct_type(type_=Model, value={"object": "model", "owned_by": "deepseek", **fields})


# --- the failure this module exists for -------------------------------------


def test_deepseek_item_without_created_reproduces_the_reported_validation_error():
    model = provider_model(id="deepseek-flash")

    # any_llm returns an instance that violates its own declared contract...
    assert isinstance(model, Model)
    assert model.created is None
    assert "created" not in model.model_fields_set

    # ...which is what crashes the old marshaling path.
    with pytest.raises(ValidationError):
        Model.model_validate(model.model_dump(include=ALLOWED_KEYS))


def test_normalized_deepseek_item_is_a_valid_model_and_cache_entry():
    entry = model_entry(provider_model(id="deepseek-flash"))

    assert entry == {
        "id": "deepseek-flash",
        "created": DEFAULT_CREATED,
        "object": MODEL_OBJECT,
        "owned_by": "deepseek",
    }
    assert set(entry) == ALLOWED_KEYS
    assert json.loads(json.dumps(entry)) == entry
    assert Model.model_validate(entry, strict=True).id == "deepseek-flash"
    assert ModelCacheDocument({"deepseek": [entry]}).models == {"deepseek": [entry]}


# --- normalization rules -----------------------------------------------------


@pytest.mark.parametrize("created", [None, True, "123", 1.5, [1]])
def test_missing_or_non_int_created_defaults_to_zero(created: object):
    entry = model_entry(provider_model(id="m", created=created))

    assert entry["created"] == DEFAULT_CREATED
    Model.model_validate(entry, strict=True)


def test_valid_created_and_owned_by_are_preserved():
    entry = model_entry(provider_model(id="llama3:8b", created=1_700_000_000, owned_by="library"))

    assert entry == {
        "id": "llama3:8b",
        "created": 1_700_000_000,
        "object": MODEL_OBJECT,
        "owned_by": "library",
    }


def test_missing_owned_by_defaults_to_empty_string():
    # Same class of any_llm leniency as mozilla-ai/any-llm#1083.
    model = construct_type(type_=Model, value={"id": "m", "created": 1, "object": "model"})

    assert model.owned_by is None
    assert model_entry(model)["owned_by"] == DEFAULT_OWNED_BY


def test_object_is_forced_to_model():
    entry = model_entry(provider_model(id="m", created=1, object="list"))

    assert entry["object"] == MODEL_OBJECT


@pytest.mark.parametrize(
    "fields",
    [{"id": None}, {"id": ""}, {"id": 123}, {"note": "id is missing"}],
    ids=["id-none", "id-empty", "id-not-str", "id-absent"],
)
def test_model_without_usable_id_is_dropped(fields: dict[str, object]):
    model = construct_type(type_=Model, value={"object": "model", "owned_by": "deepseek", **fields})

    assert model_entry(model) is None


def test_model_entries_keeps_valid_entries_and_drops_unusable_ones():
    no_id = construct_type(type_=Model, value={"object": "model", "owned_by": "deepseek"})
    entries = model_entries([no_id, provider_model(id="deepseek-chat")])

    assert entries == [
        {
            "id": "deepseek-chat",
            "created": DEFAULT_CREATED,
            "object": MODEL_OBJECT,
            "owned_by": "deepseek",
        }
    ]
