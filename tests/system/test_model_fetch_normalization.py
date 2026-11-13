"""System tests: provider model fetch → manager → cache for DeepSeek-shaped data.

DeepSeek's ``GET /models`` omits ``created``; the openai SDK constructs the
``Model`` leniently, so ``any_llm`` returns an object whose ``created`` is
``None`` (the reported crash).  These tests reproduce that payload using the
SDK's own lenient constructor, run the real ``ListModelWorker`` and
``ModelManager`` with the real ``ModelCacheStore``, and check the app ends up
with valid models and a valid cache file.  Only the provider HTTP client is
stubbed: no network, no GUI.
"""

from __future__ import annotations

import json
import logging

import pytest
from any_llm import LLMProvider
from any_llm.types.model import Model
from openai._models import construct_type

from barbaros.model_cache import ModelCacheStore
from barbaros.model_manager import CachePolicy, ModelManager, ProviderMeta
from barbaros.workers import ListModelWorker

DEEPSEEK = ProviderMeta("deepseek", LLMProvider.DEEPSEEK)
EXPECTED_ENTRIES = [
    {"id": "deepseek-flash", "created": 0, "object": "model", "owned_by": "deepseek"},
    {"id": "deepseek-v4-pro", "created": 0, "object": "model", "owned_by": "deepseek"},
]


class FakeProviderClient:
    """Stands in for the any_llm client; returns lenient openai ``Model`` instances."""

    def __init__(self, models: list[Model]) -> None:
        self._models = models

    def list_models(self) -> list[Model]:
        return list(self._models)


class StubProvider:
    """The ``ProviderClient`` surface ``ListModelWorker`` uses."""

    def __init__(self, meta: ProviderMeta, models: list[Model]) -> None:
        self.meta = meta
        self._models = models

    def client(self) -> FakeProviderClient:
        return FakeProviderClient(self._models)


def lenient_model(**fields: object) -> Model:
    return construct_type(type_=Model, value={"object": "model", "owned_by": "deepseek", **fields})


def deepseek_models() -> list[Model]:
    return [lenient_model(id="deepseek-flash"), lenient_model(id="deepseek-v4-pro")]


def run_worker(models: list[Model]) -> str:
    """Run the real worker synchronously and return its marshaled model list."""
    worker = ListModelWorker(StubProvider(DEEPSEEK, models))
    finished: list[tuple[ProviderMeta, str]] = []
    errors: list[tuple[ProviderMeta, str]] = []
    worker.finished.connect(lambda provider, payload: finished.append((provider, payload)))
    worker.error.connect(lambda provider, message: errors.append((provider, message)))

    worker.run()

    assert errors == []
    assert len(finished) == 1
    return finished[0][1]


# --- the reported scenario ---------------------------------------------------


def test_deepseek_models_without_created_reach_manager_and_cache(tmp_path):
    store = ModelCacheStore(path=tmp_path / "models.json")
    manager = ModelManager(cache=store)
    manager.add(DEEPSEEK)
    reported_errors: list[str] = []
    manager.error.connect(reported_errors.append)

    payload = run_worker(deepseek_models())
    assert json.loads(payload) == EXPECTED_ENTRIES

    manager._on_fetching_finished(DEEPSEEK, payload)

    models = manager[DEEPSEEK].models
    assert [model.id for model in models] == ["deepseek-flash", "deepseek-v4-pro"]
    assert [model.created for model in models] == [0, 0]
    assert reported_errors == []

    document = json.loads((tmp_path / "models.json").read_text(encoding="utf-8"))
    assert document == {"version": 1, "models": {"deepseek": EXPECTED_ENTRIES}}


def test_cached_deepseek_models_restore_after_restart(tmp_path):
    path = tmp_path / "models.json"
    first = ModelManager(cache=ModelCacheStore(path=path))
    first.add(DEEPSEEK)
    first._on_fetching_finished(DEEPSEEK, run_worker(deepseek_models()))

    second = ModelManager(cache=ModelCacheStore(path=path))
    second.add(DEEPSEEK, cache_policy=CachePolicy.RESTORE)

    models = second[DEEPSEEK].models
    assert [model.id for model in models] == ["deepseek-flash", "deepseek-v4-pro"]
    assert [model.created for model in models] == [0, 0]


# --- defence in depth of the worker→manager hand-off -------------------------


def test_worker_drops_unusable_model_entries_and_logs(caplog):
    no_id = construct_type(type_=Model, value={"object": "model", "owned_by": "deepseek"})

    with caplog.at_level(logging.WARNING, logger="barbaros.workers"):
        payload = run_worker([no_id, lenient_model(id="deepseek-flash")])

    assert [entry["id"] for entry in json.loads(payload)] == ["deepseek-flash"]
    assert "returned 1 unusable model entries" in caplog.text


def test_invalid_fetched_entry_is_skipped_not_fatal(caplog):
    manager = ModelManager()
    manager.add(DEEPSEEK)
    malformed_entry = {"id": "broken", "created": None, "object": "model", "owned_by": ""}
    valid_entry = EXPECTED_ENTRIES[0]

    with caplog.at_level(logging.WARNING, logger="barbaros.model_manager"):
        manager._on_fetching_finished(DEEPSEEK, json.dumps([malformed_entry, valid_entry]))

    assert [model.id for model in manager[DEEPSEEK].models] == ["deepseek-flash"]
    assert "skipped 1 invalid fetched model entries" in caplog.text


@pytest.mark.parametrize("payload", ["not json", "{}", "null", '{"models": []}'])
def test_malformed_worker_payload_reports_error_without_raising(payload: str):
    manager = ModelManager()
    manager.add(DEEPSEEK)
    reported_errors: list[str] = []
    manager.error.connect(reported_errors.append)

    manager._on_fetching_finished(DEEPSEEK, payload)  # must not raise out of the slot

    assert reported_errors
    assert "invalid model list payload" in reported_errors[0]
    assert manager[DEEPSEEK].models == []
