"""Normalization of provider-reported model lists into app model entries.

``any_llm`` exposes model-list items as ``openai.types.model.Model`` instances
(``any_llm.types.model.Model`` is that class), where ``created: int`` is a
required field.  Provider list endpoints are external, untrusted data and do
not all return it: DeepSeek's ``GET /models`` omits ``created`` (see
https://api-docs.deepseek.com/api/list-models), and other providers omit
``owned_by`` (mozilla-ai/any-llm#1083).  The openai SDK builds responses with
``construct_type`` (lenient, no pydantic validation) and any-llm passes an
already constructed ``Model`` through unchanged, so a returned instance can
silently violate the declared contract: ``model.created is None``.

The app needs the invariant "a model entry is a valid ``Model``" because model
lists are validated with pydantic, stored in the model cache and restored on
startup.  Normalization happens here, at the provider boundary, once:

* only the model-cache allowlist is kept (``id/created/object/owned_by``);
* ``object`` is always ``"model"`` — it is a constant of the app's model type;
* a missing/invalid ``created`` becomes ``0`` (the app never uses it; a
  synthetic value keeps the entry a valid ``Model``);
* a missing/invalid ``owned_by`` becomes ``""``;
* entries without a usable ``id`` are dropped — a model that cannot be
  identified cannot be listed or selected.

The output shape equals ``ModelCacheDocument.ALLOWED_MODEL_KEYS``, so fetched
and restored lists have one representation.
"""

from __future__ import annotations

from collections.abc import Sequence

from any_llm.types.model import Model

#: ``created`` is required by ``Model`` but unused by the app.
DEFAULT_CREATED = 0
DEFAULT_OWNED_BY = ""
MODEL_OBJECT = "model"


def model_entry(model: Model) -> dict | None:
    """Convert one provider model to an allowlisted, schema-valid entry.

    ``None`` means the model is unusable (no valid ``id``) and must be dropped.
    """
    model_id = getattr(model, "id", None)
    if not isinstance(model_id, str) or not model_id:
        return None

    created = getattr(model, "created", None)
    owned_by = getattr(model, "owned_by", None)
    return {
        "id": model_id,
        "created": created if type(created) is int else DEFAULT_CREATED,
        "object": MODEL_OBJECT,
        "owned_by": owned_by if isinstance(owned_by, str) else DEFAULT_OWNED_BY,
    }


def model_entries(models: Sequence[Model]) -> list[dict]:
    """Convert a provider model list, dropping unusable entries."""
    entries = []
    for model in models:
        entry = model_entry(model)
        if entry is not None:
            entries.append(entry)
    return entries
