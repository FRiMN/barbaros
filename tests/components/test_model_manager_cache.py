"""Component tests for the ``ModelManager`` / model-cache integration.

Covers docs/model-cache-storage.md §7.2 (component level, items 1-12).
``ModelManager`` knows only a ``load``/``save`` port, so a fake store is enough
here: these tests stay independent of the JSON file format, Qt, and any_llm's
HTTP clients.  The real ``ModelCacheStore`` is covered by its unit tests.
"""

import json
import threading
from copy import deepcopy

import pytest
from any_llm import LLMProvider
from any_llm.types.model import Model
from PySide6.QtCore import QObject, Signal

from barbaros.model_manager import CachePolicy, ModelManager, ProviderMeta


class FakeStore:
    """In-memory stand-in for ``ModelCacheStore`` with observable I/O.

    ``save`` replaces ``data`` with the snapshot it received, mirroring the real
    store's full-file atomic replace; a failed save leaves ``data`` untouched.
    Snapshots are recorded for every call, including failed ones, so tests can
    assert what the manager *attempted* to persist.
    """

    def __init__(
        self,
        data: dict[str, list[object]] | None = None,
        *,
        raise_on_load: bool = False,
        raise_on_save: bool = False,
        return_false_on_save: bool = False,
    ) -> None:
        self._lock = threading.Lock()
        self._data = deepcopy(data) if data is not None else {}
        self.raise_on_load = raise_on_load
        self.raise_on_save = raise_on_save
        self.return_false_on_save = return_false_on_save
        self.load_calls = 0
        self.save_calls = 0
        self.saved_snapshots: list[dict[str, list[dict]]] = []

    @property
    def data(self) -> dict[str, list[object]]:
        with self._lock:
            return deepcopy(self._data)

    def replace_data(self, data: dict[str, list[object]]) -> None:
        """Change what the next ``load`` returns (simulates an external write)."""
        with self._lock:
            self._data = deepcopy(data)

    def load(self) -> dict[str, list[object]]:
        with self._lock:
            self.load_calls += 1
            if self.raise_on_load:
                raise OSError("simulated load failure")
            return deepcopy(self._data)

    def save(self, models: dict[str, list[dict]]) -> bool:
        snapshot = deepcopy(models)
        with self._lock:
            self.save_calls += 1
            self.saved_snapshots.append(snapshot)
            if self.raise_on_save:
                raise OSError("simulated disk failure")
            if self.return_false_on_save:
                return False
            self._data = deepcopy(snapshot)
            return True


def cache_entry(model_id: str = "model-1", **overrides: object) -> dict:
    """One model entry in the allowlisted cache shape from the plan (§4.2)."""
    entry: dict = {
        "id": model_id,
        "created": 1_710_000_000,
        "object": "model",
        "owned_by": "tester",
    }
    entry.update(overrides)
    return entry


def make_model(model_id: str) -> Model:
    """A real ``any_llm`` Model as produced by ``ListModelWorker``."""
    return Model.model_validate(cache_entry(model_id))


P1 = ProviderMeta("p1", LLMProvider.OLLAMA)
P2 = ProviderMeta("p2", LLMProvider.OLLAMA)


# --- 1-2: no I/O unless explicitly restoring --------------------------------


def test_constructor_does_no_cache_io():
    # A store that would blow up on load makes an accidental read fail loudly.
    store = FakeStore(data={"p1": [cache_entry("cached")]}, raise_on_load=True)

    manager = ModelManager(cache=store)

    assert manager == {}
    assert store.load_calls == 0
    assert store.save_calls == 0


def test_add_default_ignore_policy_does_not_touch_cache():
    store = FakeStore(data={"p1": [cache_entry("cached")]})
    manager = ModelManager(cache=store)

    manager.add(P1)

    assert list(manager[P1].models) == []
    assert store.load_calls == 0
    assert store.save_calls == 0


# --- 3-4: RESTORE reads the current store on every call ----------------------


def test_add_restore_loads_once_per_call_and_ignores_foreign_providers():
    store = FakeStore(
        data={
            "p1": [cache_entry("p1-a"), cache_entry("p1-b")],
            "p2": [cache_entry("p2-a")],
        }
    )
    manager = ModelManager(cache=store)

    manager.add(P1, cache_policy=CachePolicy.RESTORE)

    assert store.load_calls == 1
    assert store.save_calls == 0
    assert set(manager) == {"p1"}
    assert [model.id for model in manager[P1].models] == ["p1-a", "p1-b"]

    manager.add(P1, cache_policy=CachePolicy.RESTORE)

    assert store.load_calls == 2
    assert [model.id for model in manager[P1].models] == ["p1-a", "p1-b"]


def test_repeated_restore_reads_current_store_and_removed_record_stays_gone():
    store = FakeStore(data={"p1": [cache_entry("first")]})
    manager = ModelManager(cache=store)
    manager.add(P1, cache_policy=CachePolicy.RESTORE)
    assert [model.id for model in manager[P1].models] == ["first"]

    # The store changed behind the manager's back; RESTORE is not a one-shot
    # snapshot, it reads the file again on every call.
    store.replace_data({"p1": [cache_entry("second")]})
    manager.add(P1, cache_policy=CachePolicy.RESTORE)
    assert [model.id for model in manager[P1].models] == ["second"]
    assert store.load_calls == 2

    # remove() persists a snapshot without p1, so the record is gone for good.
    manager.remove(P1.name)
    assert "p1" not in store.data

    manager.add(P1, cache_policy=CachePolicy.RESTORE)
    assert list(manager[P1].models) == []
    assert store.load_calls == 3


def test_update_does_not_restore_old_models():
    store = FakeStore(data={"p1": [cache_entry("cached")]})
    manager = ModelManager(cache=store)
    manager.add(P1, cache_policy=CachePolicy.RESTORE)
    assert [model.id for model in manager[P1].models] == ["cached"]

    manager.update(P1)

    assert list(manager[P1].models) == []
    # update() re-adds with the default IGNORE policy: no cache read.
    assert store.load_calls == 1


# --- 5-6: mutations persist a full snapshot ---------------------------------


def test_remove_drops_provider_and_saves_snapshot():
    store = FakeStore()
    manager = ModelManager(cache=store)
    manager.add(P1)
    manager.add(P2)
    manager.set_models(P1, [make_model("p1-a")])
    removed: list[str] = []
    manager.removed.connect(lambda name: removed.append(name))

    manager.remove(P1.name)

    assert set(manager) == {"p2"}
    assert removed == ["p1"]
    # One save from set_models, one from remove(); no separate cleanup of
    # intermediate state is needed.
    assert store.save_calls == 2
    assert store.saved_snapshots[-1] == {"p2": []}
    assert store.data == {"p2": []}


def test_set_models_saves_full_snapshot_and_remove_prunes_it():
    store = FakeStore()
    manager = ModelManager(cache=store)
    manager.add(P1)
    manager.add(P2)
    assert store.save_calls == 0  # add() itself never writes

    manager.set_models(P1, [make_model("p1-a")])

    assert store.save_calls == 1
    assert store.saved_snapshots[-1] == {"p1": [cache_entry("p1-a")], "p2": []}

    manager.remove(P2.name)

    assert store.save_calls == 2
    assert store.saved_snapshots[-1] == {"p1": [cache_entry("p1-a")]}

    manager.set_models(P1, [make_model("p1-a"), make_model("p1-b")])

    assert store.save_calls == 3
    assert store.saved_snapshots[-1] == {
        "p1": [cache_entry("p1-a"), cache_entry("p1-b")],
    }


# --- 7: no store means no I/O and no file -----------------------------------


def test_manager_without_store_does_no_io_and_creates_no_file(
    data_home, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    manager = ModelManager()
    manager.add(P1)
    manager.set_models(P1, [make_model("p1-a")])
    manager.remove(P1.name)

    # No implicit default store: nothing appears in the working directory or
    # under XDG_DATA_HOME (data_home is nested in tmp_path).
    assert list(tmp_path.iterdir()) == []
    assert list(data_home.rglob("*")) == []


# --- 8: a failed save must not lose the in-memory update or raise -----------


@pytest.mark.parametrize(
    "store_kwargs",
    [
        pytest.param({"raise_on_save": True}, id="save-raises-oserror"),
        pytest.param({"return_false_on_save": True}, id="save-returns-false"),
    ],
)
def test_save_failure_keeps_memory_update_and_emits_signal(store_kwargs):
    store = FakeStore(**store_kwargs)
    manager = ModelManager(cache=store)
    manager.add(P1)
    emitted: list[int] = []
    manager.loaded_list_models.connect(lambda: emitted.append(1))

    manager.set_models(P1, [make_model("p1-a")])  # must not raise

    assert [model.id for model in manager[P1].models] == ["p1-a"]
    assert emitted == [1]
    assert store.save_calls == 1
    assert store.saved_snapshots[-1] == {"p1": [cache_entry("p1-a")]}


# --- 9: concurrent set_models under the RLock -------------------------------


def test_concurrent_set_models_keeps_full_snapshot(make_models):
    store = FakeStore()
    manager = ModelManager(cache=store)
    manager.add(P1)
    manager.add(P2)
    p1_models = [Model.model_validate(entry) for entry in make_models(3, prefix="p1")]
    p2_models = [Model.model_validate(entry) for entry in make_models(2, prefix="p2")]
    barrier = threading.Barrier(2)
    errors: list[Exception] = []
    emitted: list[int] = []
    manager.loaded_list_models.connect(lambda: emitted.append(1))

    def run_set_models(provider: ProviderMeta, models: list[Model]) -> None:
        try:
            barrier.wait(timeout=5)
            manager.set_models(provider, models)
        except Exception as exc:  # surfaced by the assertions below
            errors.append(exc)

    threads = [
        threading.Thread(target=run_set_models, args=(P1, p1_models), name="set-models-p1"),
        threading.Thread(target=run_set_models, args=(P2, p2_models), name="set-models-p2"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert len(emitted) == 2
    assert len(store.saved_snapshots) == 2

    for snapshot in store.saved_snapshots:
        # Every recorded snapshot is a complete, JSON-serializable document,
        # never a torn half-update; both providers were added before the race.
        assert set(snapshot) == {"p1", "p2"}
        assert json.loads(json.dumps(snapshot)) == snapshot

    # The last snapshot must contain both providers' models: the mutation and
    # the snapshot it saves happen under the same lock.
    last_snapshot = store.saved_snapshots[-1]
    assert [entry["id"] for entry in last_snapshot["p1"]] == ["p1-0", "p1-1", "p1-2"]
    assert [entry["id"] for entry in last_snapshot["p2"]] == ["p2-0", "p2-1"]


# --- 10: strict validation on RESTORE ---------------------------------------


@pytest.mark.parametrize(
    "invalid_entry",
    [
        pytest.param(cache_entry("bad", created=True), id="created-bool"),
        pytest.param(cache_entry("bad", created=None), id="created-none"),
        pytest.param(cache_entry("bad", created="1"), id="created-string"),
        pytest.param(cache_entry("bad", created=1.0), id="created-float"),
        pytest.param(
            {"created": 1, "object": "model", "owned_by": "tester"},
            id="missing-id",
        ),
        pytest.param(cache_entry("bad", object="completion"), id="wrong-object"),
        pytest.param(
            {"id": 7, "created": 1, "object": "model", "owned_by": "tester"},
            id="non-string-id",
        ),
        pytest.param("not-a-dict", id="string-entry"),
        pytest.param(None, id="none-entry"),
    ],
)
def test_restore_drops_invalid_entry_and_keeps_valid_neighbours(invalid_entry):
    store = FakeStore(
        data={
            "p1": [
                cache_entry("before"),
                invalid_entry,
                cache_entry("after"),
            ]
        }
    )
    manager = ModelManager(cache=store)

    manager.add(P1, cache_policy=CachePolicy.RESTORE)

    assert [model.id for model in manager[P1].models] == ["before", "after"]
    assert store.save_calls == 0


# --- 11: foreign providers are ignored and pruned by the first save ---------


def test_restore_ignores_foreign_providers_and_first_save_prunes_them():
    store = FakeStore(
        data={
            "p1": [cache_entry("p1-a")],
            "ghost": [cache_entry("ghost-a")],
        }
    )
    manager = ModelManager(cache=store)

    manager.add(P1, cache_policy=CachePolicy.RESTORE)

    assert set(manager) == {"p1"}
    assert [model.id for model in manager[P1].models] == ["p1-a"]

    manager.set_models(P1, [make_model("p1-b")])

    # The full snapshot is self-pruning: no separate prune/discard step.
    assert store.save_calls == 1
    assert store.data == {"p1": [cache_entry("p1-b")]}


# --- 12: default_providers() is a factory -----------------------------------


def test_default_providers_returns_fresh_list_of_fresh_instances():
    first = ModelManager.default_providers()
    second = ModelManager.default_providers()

    assert first is not second
    assert first[0] is not second[0]
    assert all(isinstance(provider, ProviderMeta) for provider in first)
    assert first[0].name == "ollama"
    assert first[0].provider_type is LLMProvider.OLLAMA

    first[0].name = "mutated"
    first.append(ProviderMeta("extra", LLMProvider.OLLAMA))

    assert second[0].name == "ollama"
    assert len(ModelManager.default_providers()) == 1


# --- thread hand-off --------------------------------------------------------


def test_fetch_results_are_applied_in_the_manager_thread(monkeypatch, wait_until):
    """Worker results are queued to the manager's thread, never applied in the worker.

    This is what keeps ``set_models``/``_persist`` safe from ``QThread.terminate()``:
    a terminated worker holding a Python lock would leak it forever.
    """
    import barbaros.workers as workers

    applied_in: list[str] = []

    class FakeWorker(QObject):
        finished = Signal(ProviderMeta, str)
        error = Signal(ProviderMeta, str)

        def __init__(self, provider):
            super().__init__()
            self.provider = provider.meta

        def run(self):
            self.finished.emit(self.provider, json.dumps([cache_entry("fetched")]))

        def connect_terminate(self, thread):
            for signal in (self.finished, self.error):
                signal.connect(self.deleteLater)
                signal.connect(thread.quit)

    monkeypatch.setattr(workers, "ListModelWorker", FakeWorker)
    manager = ModelManager(cache=FakeStore())
    manager.add(P1)
    original_set_models = manager.set_models

    def recording_set_models(*args, **kwargs):
        applied_in.append(threading.current_thread().name)
        return original_set_models(*args, **kwargs)

    monkeypatch.setattr(manager, "set_models", recording_set_models)

    manager._start_fetching_models(manager[P1])

    assert wait_until(lambda: bool(manager[P1].models))
    assert applied_in == [threading.current_thread().name]
    assert [model.id for model in manager[P1].models] == ["fetched"]

    manager.shutdown()


def test_set_models_for_removed_provider_is_ignored():
    manager = ModelManager()
    manager.add(P1)
    manager.remove("p1")

    manager.set_models(P1, [make_model("late")])

    assert "p1" not in manager


def test_restore_load_failure_is_fail_safe():
    store = FakeStore(raise_on_load=True)
    manager = ModelManager(cache=store)

    manager.add(P1, cache_policy=CachePolicy.RESTORE)

    assert manager[P1].models == []
