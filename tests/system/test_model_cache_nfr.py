"""Non-functional tests for the model-list cache (docs/model-cache-storage.md §7.2).

Timings are deliberately compared against wide budgets: these tests guard the
order of magnitude of the chosen design on a loaded machine, not micro-timings.
Both tests are marked ``slow`` because they build a 25k-model cache.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from barbaros.main_window import MainWindow
from barbaros.model_cache import ModelCacheStore

pytestmark = pytest.mark.slow

LARGE_CACHE_MODELS = 25_000
# 3 providers: MAX_MODELS_PER_PROVIDER is 10k, so one provider would be
# truncated and the dataset would no longer be ~2 MiB.
LARGE_CACHE_PROVIDER_COUNTS = {
    "ollama": 8334,
    "provider-1": 8333,
    "provider-2": 8333,
}
CACHE_OPERATION_BUDGET_SECONDS = 0.5
STARTUP_OVERHEAD_BUDGET_SECONDS = 1.5


# --- helpers ---------------------------------------------------------------


def cache_path(data_home: Path) -> Path:
    """Default cache file for the application name set by the ``qapp`` fixture."""
    return Path(data_home) / "barbaros" / "models.json"


def large_cache_data(make_models) -> dict[str, list[dict]]:
    """~2 MiB of valid cache entries spread over three providers."""
    return {
        name: make_models(count, prefix=f"{name}-model")
        for name, count in LARGE_CACHE_PROVIDER_COUNTS.items()
    }


def configure_large_cache_providers(fake_settings) -> None:
    """Configure the providers the large cache has records for.

    Empty and loaded measurements must run with the same provider list, so the
    only difference between them is the cache file.
    """
    providers = [
        {"name": name, "provider_type": "ollama", "api_base": None}
        for name in LARGE_CACHE_PROVIDER_COUNTS
    ]
    fake_settings.setValue("main_window/llm_providers", json.dumps(providers))
    fake_settings.sync()


def startup_seconds(app, *, expected_models: int | None = None) -> float:
    """Construct one ``MainWindow`` and return how long ``__init__`` took."""
    started = time.perf_counter()
    window = MainWindow(app=app)
    elapsed = time.perf_counter() - started
    try:
        if expected_models is not None:
            restored = sum(len(client.models) for client in window.model_manager.values())
            assert restored == expected_models, f"restored {restored} cached models"
    finally:
        window.model_manager.shutdown()
        window.deleteLater()
    return elapsed


# --- NFR 1: store load/save ------------------------------------------------


def test_cache_load_and_save_25k_models_within_budget(tmp_path, make_models):
    data = large_cache_data(make_models)
    store = ModelCacheStore(tmp_path / "models.json")

    # One warm-up pass on a throwaway path (imports, allocator, page cache).
    warmup = ModelCacheStore(tmp_path / "warmup-models.json")
    assert warmup.save(data) is True
    assert warmup.load()

    started = time.perf_counter()
    assert store.save(data) is True
    save_seconds = time.perf_counter() - started

    started = time.perf_counter()
    loaded = store.load()
    load_seconds = time.perf_counter() - started

    assert sum(len(entries) for entries in loaded.values()) == LARGE_CACHE_MODELS
    assert store.path is not None
    assert store.path.stat().st_size > 1_500_000  # actually ~2 MiB of JSON

    assert save_seconds < CACHE_OPERATION_BUDGET_SECONDS, (
        f"save() of 25k models took {save_seconds:.3f}s "
        f"(budget {CACHE_OPERATION_BUDGET_SECONDS:.1f}s)"
    )
    assert load_seconds < CACHE_OPERATION_BUDGET_SECONDS, (
        f"load() of 25k models took {load_seconds:.3f}s "
        f"(budget {CACHE_OPERATION_BUDGET_SECONDS:.1f}s)"
    )


# --- NFR 2: startup with a large cache -------------------------------------


def test_startup_with_25k_cached_models_is_not_much_slower(
    data_home, fake_app, fake_settings, make_models, cache_doc, write_cache
):
    configure_large_cache_providers(fake_settings)

    # Warm-up: one-time Qt/widget imports are common to both measurements.
    startup_seconds(fake_app)

    # min() of a few samples: robust to occasional scheduler/IO spikes.
    empty_seconds = min(startup_seconds(fake_app) for _ in range(3))

    write_cache(cache_path(data_home), cache_doc(large_cache_data(make_models)))
    loaded_seconds = min(
        startup_seconds(fake_app, expected_models=LARGE_CACHE_MODELS) for _ in range(3)
    )

    overhead = loaded_seconds - empty_seconds
    assert overhead <= STARTUP_OVERHEAD_BUDGET_SECONDS, (
        f"startup with 25k cached models is slower by {overhead:.3f}s "
        f"(empty {empty_seconds:.3f}s, loaded {loaded_seconds:.3f}s, "
        f"budget {STARTUP_OVERHEAD_BUDGET_SECONDS:.1f}s)"
    )
