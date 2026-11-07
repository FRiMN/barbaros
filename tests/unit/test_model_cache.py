"""Unit tests for :class:`barbaros.model_cache.ModelCacheStore`.

Covers the unit section of the test matrix in ``docs/model-cache-storage.md``
(§7.2, items 1-13). No QApplication/display is needed: only the default-path
tests touch ``QCoreApplication.setApplicationName`` (a static setting), and
file-based tests use an injected ``tmp_path``.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from barbaros import model_cache
from barbaros.model_cache import ModelCacheStore, cache_path_from_config

POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="POSIX file semantics")


# --- helpers ---------------------------------------------------------------


def _model(
    model_id: str = "m1",
    *,
    created: object = 1_700_000_000,
    object_: object = "model",
    owned_by: object = "lib",
    **extra: object,
) -> dict:
    entry: dict = {
        "id": model_id,
        "created": created,
        "object": object_,
        "owned_by": owned_by,
    }
    entry.update(extra)
    return entry


def _write_raw(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _write_document(path: Path, models: object, version: object = 1) -> None:
    _write_raw(path, json.dumps({"version": version, "models": models}))


def _make_store(tmp_path: Path, name: str = "models.json") -> ModelCacheStore:
    return ModelCacheStore(tmp_path / "appdata" / name)


def _patch_standard_paths(
    monkeypatch: pytest.MonkeyPatch, base: object
) -> list[object]:
    """Replace ``PySide6.QtCore.QStandardPaths`` with a fake returning ``base``.

    The store imports it lazily from the module, so patching the module
    attribute is enough.
    """
    import PySide6.QtCore as qtcore

    calls: list[object] = []

    class FakeQStandardPaths:
        class StandardLocation:
            AppDataLocation = 0

        @staticmethod
        def writableLocation(location: object) -> object:
            calls.append(location)
            if isinstance(base, BaseException):
                raise base
            return base

    monkeypatch.setattr(qtcore, "QStandardPaths", FakeQStandardPaths)
    return calls


# --- §7.2 item 1: round-trip ------------------------------------------------


def test_round_trip_valid_data_is_sanitized_and_stable(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    data = {
        "ollama remote": [
            _model("llama3:8b", created=1710000000, owned_by="library"),
            _model("mïstral-ü", created=0, owned_by=""),
        ],
        "openrouter": [_model("openai/gpt-4o", created=42, owned_by="openrouter")],
    }

    assert store.save(data) is True
    assert store.load() == data
    assert store.load() == store.load()  # deterministic

    raw = store.path.read_bytes()
    assert raw.startswith(b'{"version":1,"models":{')
    assert b"m\xc3\xafstral-\xc3\xbc" in raw  # ensure_ascii=False
    assert b", " not in raw and b": " not in raw  # compact separators


def test_round_trip_drops_empty_providers_and_disallowed_keys(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    data = {
        "empty": [],
        "p": [_model("m1", api_key="secret", api_base="http://evil", extra={"x": 1})],
    }

    assert store.save(data) is True
    assert store.load() == {"p": [_model("m1")]}


# --- §7.2 item 2: missing file / directory ----------------------------------


def test_missing_file_returns_empty_and_creates_nothing(tmp_path: Path) -> None:
    store = _make_store(tmp_path)

    assert store.load() == {}
    assert store.path is not None
    assert not store.path.exists()
    assert not store.path.parent.exists()  # load must not create the directory


def test_directory_instead_of_file_returns_empty(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.path is not None
    store.path.mkdir(parents=True)

    assert store.load() == {}


def test_path_resolution_failure_is_fail_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_standard_paths(monkeypatch, RuntimeError("QStandardPaths is broken"))
    store = ModelCacheStore()

    assert store.path is None  # the constructor degraded to a disabled store
    assert store.load() == {}
    assert store.save({"p": [_model()]}) is False


@POSIX_ONLY
def test_fifo_instead_of_file_is_ignored_without_blocking(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True)
    os.mkfifo(store.path)

    assert store.load() == {}
    assert stat.S_ISFIFO(store.path.stat().st_mode)


def test_unopenable_path_never_raises(tmp_path: Path) -> None:
    # A NUL byte is invalid in a path: os.open() raises ValueError, which the
    # fail-safe boundary must swallow like any OSError.
    store = ModelCacheStore(tmp_path / "bad\x00name.json")

    assert store.load() == {}
    assert store.save({"p": [_model()]}) is False
    assert not (tmp_path / "bad\x00name.json").exists()


# --- §7.2 item 3: corrupt JSON ----------------------------------------------

_CORRUPT_PAYLOADS = [
    pytest.param(b'{"version":1,"models":', id="truncated"),
    pytest.param(b"definitely not json", id="garbage"),
    pytest.param(b"", id="empty-file"),
    pytest.param(b"   \n\t", id="whitespace-only"),
    pytest.param(b"\xef\xbb\xbf" + b'{"version":1,"models":{}}', id="utf8-bom"),
    pytest.param(b"\xff\xfe\x00\x01", id="non-utf8"),
]


@pytest.mark.parametrize("payload", _CORRUPT_PAYLOADS)
def test_corrupt_json_returns_empty_and_keeps_file(
    tmp_path: Path, payload: bytes
) -> None:
    store = _make_store(tmp_path)
    _write_raw(store.path, payload)

    assert store.load() == {}
    assert store.path.is_file()  # corrupt cache is not deleted...
    assert store.path.read_bytes() == payload  # ...and not rewritten


# --- §7.2 item 4: wrong schema, neighbours kept -----------------------------


@pytest.mark.parametrize(
    "document", [[], "text", None, 42, True], ids=["list", "str", "null", "int", "bool"]
)
def test_top_level_non_object_returns_empty(tmp_path: Path, document: object) -> None:
    store = _make_store(tmp_path)
    _write_raw(store.path, json.dumps(document))

    assert store.load() == {}


@pytest.mark.parametrize(
    "models_section", [[], "x", None, 42], ids=["list", "str", "null", "int"]
)
def test_models_section_not_object_returns_empty(
    tmp_path: Path, models_section: object
) -> None:
    store = _make_store(tmp_path)
    _write_document(store.path, models_section)

    assert store.load() == {}


def test_missing_models_section_returns_empty(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    _write_raw(store.path, json.dumps({"version": 1}))

    assert store.load() == {}


@pytest.mark.parametrize(
    "provider_value",
    [{}, "string", None, 42, True],
    ids=["object", "str", "null", "int", "bool"],
)
def test_provider_value_not_list_is_dropped(
    tmp_path: Path, provider_value: object
) -> None:
    store = _make_store(tmp_path)
    _write_document(store.path, {"p": provider_value, "ok": [_model("m")]})

    assert store.load() == {"ok": [_model("m")]}


def test_empty_provider_list_is_dropped(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    _write_document(store.path, {"p": []})

    assert store.load() == {}


_INVALID_MODEL_ENTRIES = [
    pytest.param("not a dict", id="string"),
    pytest.param(42, id="int"),
    pytest.param(None, id="null"),
    pytest.param([], id="list"),
    pytest.param({}, id="empty-dict"),
    pytest.param(_model(""), id="empty-id"),
    pytest.param(_model(5), id="non-str-id"),  # deliberately not a str
    pytest.param(_model("m" * 1025), id="id-too-long"),
    pytest.param(
        {"id": "m", "object": "model", "owned_by": "lib"}, id="created-missing"
    ),
    pytest.param(_model(created=True), id="created-true"),
    pytest.param(_model(created=False), id="created-false"),
    pytest.param(_model(created=1.0), id="created-float"),
    pytest.param(_model(created="1"), id="created-string"),
    pytest.param(_model(created=None), id="created-null"),
    pytest.param(_model(object_="chat.completion"), id="wrong-object"),
    pytest.param({"id": "m", "created": 1, "owned_by": "lib"}, id="object-missing"),
    pytest.param(_model(owned_by=5), id="owned-by-non-str"),
    pytest.param({"id": "m", "created": 1, "object": "model"}, id="owned-by-missing"),
    pytest.param(_model(owned_by="o" * 257), id="owned-by-too-long"),
]


@pytest.mark.parametrize("invalid_entry", _INVALID_MODEL_ENTRIES)
def test_invalid_model_entries_are_skipped_valid_neighbours_kept(
    tmp_path: Path, invalid_entry: object
) -> None:
    store = _make_store(tmp_path)
    before = _model("before")
    after = _model("after")
    _write_document(store.path, {"p": [before, invalid_entry, after]})

    assert store.load() == {"p": [before, after]}


def test_length_limits_accept_exact_boundary_values(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    provider_name = "p" * store.MAX_PROVIDER_NAME_LEN
    entry = _model("m" * store.MAX_MODEL_ID_LEN, owned_by="o" * store.MAX_OWNED_BY_LEN)
    _write_document(store.path, {provider_name: [entry]})

    assert store.load() == {provider_name: [entry]}


def test_invalid_provider_names_and_values_are_dropped_on_save(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    data = {
        "": [_model("empty-name")],
        "p" * 257: [_model("too-long-name")],
        42: [_model("non-str-name")],  # deliberately not a str
        "empty": [],
        "ok": [_model("kept")],
    }

    assert store.save(data) is True
    assert store.load() == {"ok": [_model("kept")]}


def test_save_sanitizes_invalid_entries(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    data = {
        "p": [
            _model("kept-1"),
            {"id": ""},
            {"id": "x", "created": True, "object": "model", "owned_by": "lib"},
            _model("kept-2", unknown=True),
            123,  # deliberately not a dict
        ]
    }

    assert store.save(data) is True
    assert store.load() == {"p": [_model("kept-1"), _model("kept-2")]}


# --- §7.2 item 5: unknown version ------------------------------------------

_UNKNOWN_VERSIONS = [
    pytest.param(2, id="2"),
    pytest.param(0, id="0"),
    pytest.param(-1, id="negative"),
    pytest.param("1", id="string"),
    pytest.param(1.0, id="float"),
    pytest.param(True, id="bool"),
    pytest.param(None, id="null"),
]


@pytest.mark.parametrize("version", _UNKNOWN_VERSIONS)
def test_unknown_version_returns_empty_without_touching_file(
    tmp_path: Path, version: object
) -> None:
    store = _make_store(tmp_path)
    payload = json.dumps({"version": version, "models": {"p": [_model()]}}).encode(
        "utf-8"
    )
    _write_raw(store.path, payload)

    assert store.load() == {}
    assert store.path.is_file()
    assert store.path.read_bytes() == payload


# --- §7.2 item 6: oversized file -------------------------------------------


def test_oversized_file_is_ignored_without_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = _make_store(tmp_path)
    payload = b"x" * (store.MAX_FILE_BYTES + 1)
    _write_raw(store.path, payload)

    parsed: list[object] = []

    def fail_loads(*args: object, **kwargs: object) -> object:
        parsed.append((args, kwargs))
        raise AssertionError("oversized file must not be parsed")

    monkeypatch.setattr(model_cache.json, "loads", fail_loads)
    with caplog.at_level(logging.WARNING, logger="barbaros.model_cache"):
        assert store.load() == {}

    assert parsed == []
    assert store.path.read_bytes() == payload
    assert any("too large" in record.getMessage() for record in caplog.records)


def test_file_of_exact_max_size_is_still_read(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    document = json.dumps(
        {"version": 1, "models": {"p": [_model()]}}, separators=(",", ":")
    ).encode("utf-8")
    padded = document + b" " * (store.MAX_FILE_BYTES - len(document))
    assert len(padded) == store.MAX_FILE_BYTES
    _write_raw(store.path, padded)

    assert store.load() == {"p": [_model()]}


def test_save_refuses_payload_larger_than_limit(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    huge_id = "m" * store.MAX_MODEL_ID_LEN
    data = {
        "p": [_model(huge_id, created=i) for i in range(store.MAX_MODELS_PER_PROVIDER)]
    }

    assert store.save(data) is False
    assert store.path is not None
    assert not store.path.exists()
    assert not store.path.parent.exists()  # refused before touching the filesystem


# --- §7.2 item 7: atomicity -------------------------------------------------


def test_save_leaves_only_the_target_file(tmp_path: Path) -> None:
    store = _make_store(tmp_path)

    assert store.save({"p": [_model()]}) is True
    assert [entry.name for entry in store.path.parent.iterdir()] == ["models.json"]


def test_save_failure_while_replacing_keeps_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _make_store(tmp_path)
    assert store.save({"p": [_model("old")]}) is True
    old_bytes = store.path.read_bytes()

    def failing_replace(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failing_replace)

    assert store.save({"p": [_model("new")]}) is False
    assert store.path.read_bytes() == old_bytes
    assert store.load() == {"p": [_model("old")]}
    assert [entry.name for entry in store.path.parent.iterdir()] == ["models.json"]


def test_save_failure_while_serializing_keeps_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _make_store(tmp_path)
    assert store.save({"p": [_model("old")]}) is True
    old_bytes = store.path.read_bytes()

    def failing_dumps(*args: object, **kwargs: object) -> str:
        raise ValueError("cannot serialize")

    monkeypatch.setattr(model_cache.json, "dumps", failing_dumps)

    assert store.save({"p": [_model("new")]}) is False
    assert store.path.read_bytes() == old_bytes
    assert list(store.path.parent.glob("*.tmp")) == []


def test_save_failure_while_writing_cleans_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _make_store(tmp_path)
    assert store.save({"p": [_model("old")]}) is True
    old_bytes = store.path.read_bytes()

    def failing_fsync(fd: int) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "fsync", failing_fsync)

    assert store.save({"p": [_model("new")]}) is False
    assert store.path.read_bytes() == old_bytes
    assert [entry.name for entry in store.path.parent.iterdir()] == ["models.json"]


def test_save_failure_without_previous_file_leaves_no_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _make_store(tmp_path)

    def failing_replace(*args: object, **kwargs: object) -> None:
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(os, "replace", failing_replace)

    assert store.save({"p": [_model()]}) is False
    assert not store.path.exists()
    assert list(store.path.parent.glob("*.tmp")) == []


# --- §7.2 item 8: permissions ---------------------------------------------


@POSIX_ONLY
@pytest.mark.parametrize("umask", [0o022, 0o077], ids=["umask-022", "umask-077"])
def test_save_permissions_do_not_depend_on_umask(tmp_path: Path, umask: int) -> None:
    store = _make_store(tmp_path)
    previous_umask = os.umask(umask)
    try:
        assert store.save({"p": [_model()]}) is True
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700


@POSIX_ONLY
def test_save_tightens_preexisting_file_and_directory(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True)
    os.chmod(store.path.parent, 0o755)
    store.path.write_bytes(b"old")
    os.chmod(store.path, 0o644)

    assert store.save({"p": [_model()]}) is True
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700


# --- §7.2 item 9: symlinks -------------------------------------------------


@POSIX_ONLY
def test_load_does_not_follow_symlinks(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True)
    target = tmp_path / "outside.json"
    target_bytes = json.dumps({"version": 1, "models": {"p": [_model()]}}).encode(
        "utf-8"
    )
    target.write_bytes(target_bytes)
    os.symlink(target, store.path)

    assert store.load() == {}
    assert target.read_bytes() == target_bytes


@POSIX_ONLY
def test_save_replaces_symlink_without_touching_target(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.path.parent.mkdir(parents=True)
    target = tmp_path / "outside.json"
    target_bytes = b'{"keep":true}'
    target.write_bytes(target_bytes)
    os.symlink(target, store.path)

    assert store.save({"p": [_model("new")]}) is True
    assert not store.path.is_symlink()
    assert store.load() == {"p": [_model("new")]}
    assert target.read_bytes() == target_bytes


# --- §7.2 item 10: NaN, duplicates, huge ints ------------------------------


def test_save_empty_snapshot_writes_empty_document(tmp_path: Path) -> None:
    store = _make_store(tmp_path)

    assert store.save({}) is True
    assert store.path.read_bytes() == b'{"version":1,"models":{}}'
    assert store.load() == {}


@pytest.mark.parametrize(
    "bad_created",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "inf", "-inf"],
)
def test_save_drops_non_finite_created_without_exception(
    tmp_path: Path, bad_created: float
) -> None:
    store = _make_store(tmp_path)
    data = {"p": [_model(created=bad_created), _model("ok")]}

    assert store.save(data) is True
    assert store.load() == {"p": [_model("ok")]}


def test_load_skips_non_finite_created_without_exception(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    _write_raw(
        store.path,
        '{"version":1,"models":{"p":['
        '{"id":"bad","created":NaN,"object":"model","owned_by":"lib"},'
        '{"id":"ok","created":1,"object":"model","owned_by":"lib"}]}}',
    )

    assert store.load() == {"p": [_model("ok", created=1)]}


def test_load_duplicate_provider_keys_last_wins(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    _write_raw(
        store.path,
        '{"version":1,"models":{'
        '"p":[{"id":"first","created":1,"object":"model","owned_by":"lib"}],'
        '"p":[{"id":"second","created":1,"object":"model","owned_by":"lib"}]}}',
    )

    assert store.load() == {"p": [_model("second", created=1)]}


def test_load_duplicate_model_keys_last_wins(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    _write_raw(
        store.path,
        '{"version":1,"models":{"p":['
        '{"id":"a","id":"b","created":1,"object":"model","owned_by":"lib"}]}}',
    )

    assert store.load() == {"p": [_model("b", created=1)]}


def test_load_duplicate_model_entries_are_kept(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    _write_document(store.path, {"p": [_model("dup"), _model("dup")]})

    assert store.load() == {"p": [_model("dup"), _model("dup")]}


def test_huge_created_int_round_trips(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    huge = 10**400
    data = {"p": [_model(created=huge)]}

    assert store.save(data) is True
    assert store.load() == data


def test_save_unsupported_surrogate_returns_false_and_writes_nothing(
    tmp_path: Path,
) -> None:
    store = _make_store(tmp_path)
    data = {"p": [_model("\ud800")]}

    assert store.save(data) is False
    assert not store.path.exists()


# --- §7.2 item 11: disabled store ------------------------------------------


@pytest.mark.parametrize("base", ["", None], ids=["empty-string", "none"])
def test_disabled_store_is_inert_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base: object
) -> None:
    calls = _patch_standard_paths(monkeypatch, base)
    monkeypatch.chdir(tmp_path)
    store = ModelCacheStore()

    assert store.path is None
    assert store.load() == {}
    assert store.save({"p": [_model()]}) is False
    assert list(tmp_path.iterdir()) == []  # nothing written to the CWD
    assert len(calls) == 1  # location resolved once, then cached as disabled


# --- §7.2 item 12: import hygiene ------------------------------------------


def test_module_has_no_forbidden_imports_at_import_time() -> None:
    source = Path(model_cache.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_roots = {"PySide6", "keyring", "any_llm"}

    for node in tree.body:  # module-level imports only: Qt is allowed lazily
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_roots
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module.split(".")[0] not in forbidden_roots
            assert module != "barbaros.security"

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "barbaros.security"
            assert all(alias.name != "QSettings" for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in {"keyring", "any_llm"}

    print_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    assert print_calls == []


def test_fresh_import_does_not_pull_qt_keyring_or_security() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    code = (
        "import sys\n"
        "import barbaros.model_cache\n"
        "forbidden = [\n"
        "    name\n"
        "    for name in ('PySide6', 'keyring', 'any_llm', 'barbaros.security')\n"
        "    if name in sys.modules\n"
        "]\n"
        "raise SystemExit(1 if forbidden else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


# --- §7.2 item 13: default path resolution ---------------------------------


def test_default_path_is_appdata_location_models_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QCoreApplication, QStandardPaths

    data_home = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    previous_name = QCoreApplication.applicationName()
    QCoreApplication.setApplicationName("barbaros-cache-unit")
    try:
        store = ModelCacheStore()
        expected = (
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppDataLocation
                )
            )
            / "models.json"
        )

        assert expected.name == "models.json"
        assert store.path == expected
        assert store.path == expected  # a stable attribute, no re-resolution
        if sys.platform.startswith("linux"):
            assert expected.is_relative_to(data_home)
    finally:
        QCoreApplication.setApplicationName(previous_name)


def test_path_is_resolved_once_when_the_store_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "appdata"
    calls = _patch_standard_paths(monkeypatch, str(base))

    store = ModelCacheStore()

    assert store.path == base / "models.json"
    assert len(calls) == 1  # resolved eagerly in the constructor

    assert store.load() == {}
    assert store.save({"p": [_model()]}) is True
    assert store.load() == {"p": [_model()]}
    assert len(calls) == 1  # property reads and I/O never re-resolve it


def test_explicit_path_wins_without_resolving_qt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_standard_paths(
        monkeypatch, RuntimeError("QStandardPaths must not be used")
    )
    explicit_path = tmp_path / "custom" / "cache.json"
    store = ModelCacheStore(explicit_path)

    assert store.path == explicit_path
    assert store.save({"p": [_model()]}) is True
    assert store.load() == {"p": [_model()]}
    assert calls == []


# --- config override: model_cache_path -------------------------------------


def test_config_path_unset_or_empty_means_auto() -> None:
    assert cache_path_from_config(None) is None
    assert cache_path_from_config("") is None
    assert cache_path_from_config("   ") is None


def test_config_path_absolute_is_used(tmp_path: Path) -> None:
    target = tmp_path / "custom" / "models.json"
    assert cache_path_from_config(str(target)) == target


def test_config_path_expands_tilde(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cache_path_from_config("~/cache/models.json") == (
        tmp_path / "cache" / "models.json"
    )


def test_config_path_is_used_by_the_store(tmp_path: Path) -> None:
    target = tmp_path / "custom" / "models.json"
    store = ModelCacheStore(cache_path_from_config(f"  {target}  "))

    assert store.path == target
    assert store.save({"p": [_model()]}) is True
    assert store.load() == {"p": [_model()]}


@pytest.mark.parametrize("value", [1, 1.5, True, [], {}, b"/tmp/models.json"])
def test_config_path_non_string_is_ignored(
    value: object, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="barbaros.model_cache"):
        assert cache_path_from_config(value) is None

    records = [record for record in caplog.records if record.name == "barbaros.model_cache"]
    assert records
    assert all(model_cache.SETTINGS_KEY in record.getMessage() for record in records)


@pytest.mark.parametrize("value", ["cache.json", "./models.json", "../models.json"])
def test_config_path_relative_is_ignored(
    value: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="barbaros.model_cache"):
        assert cache_path_from_config(value) is None

    assert any(
        "absolute" in record.getMessage()
        for record in caplog.records
        if record.name == "barbaros.model_cache"
    )


def test_config_path_with_unknown_user_is_ignored_without_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # pathlib.expanduser() raises RuntimeError for an unresolvable ``~user``.
    with caplog.at_level(logging.WARNING, logger="barbaros.model_cache"):
        assert cache_path_from_config("~no-such-user-xyz/cache.json") is None

    assert any(
        "cannot expand" in record.getMessage()
        for record in caplog.records
        if record.name == "barbaros.model_cache"
    )


def test_config_path_hostile_value_is_logged_escaped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="barbaros.model_cache"):
        assert cache_path_from_config("rel\nforged: log line") is None

    records = [record for record in caplog.records if record.name == "barbaros.model_cache"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "\n" not in message
    assert "rel\\nforged: log line" in message  # escaped repr form, one line


# --- fail-safe boundary: unexpected internal errors -------------------------


def test_unexpected_internal_error_is_fail_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = _make_store(tmp_path)
    _write_document(store.path, {"p": [_model()]})

    def broken_sanitize(models: object) -> dict[str, list[dict]]:
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr(store, "_sanitize", broken_sanitize)
    with caplog.at_level(logging.WARNING, logger="barbaros.model_cache"):
        assert store.load() == {}

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "barbaros.model_cache"
    ]
    assert any(
        str(store.path) in message and "RuntimeError" in message
        for message in messages
    )


# --- logging contract (§4.6): warning details and log-injection safety -----


def test_load_warning_contains_path_and_exception_class(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _make_store(tmp_path)
    _write_raw(store.path, b"{not json")

    with caplog.at_level(logging.WARNING, logger="barbaros.model_cache"):
        assert store.load() == {}

    records = [
        record for record in caplog.records if record.name == "barbaros.model_cache"
    ]
    assert records
    messages = [record.getMessage() for record in records]
    assert any(
        str(store.path) in message and "JSONDecodeError" in message
        for message in messages
    )


def test_external_names_in_debug_logs_are_escaped_and_truncated(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _make_store(tmp_path)
    hostile_name = "x" * 300 + "\nforged: log line"
    _write_document(store.path, {hostile_name: [_model()]})

    with caplog.at_level(logging.DEBUG, logger="barbaros.model_cache"):
        assert store.load() == {}

    records = [
        record for record in caplog.records if record.name == "barbaros.model_cache"
    ]
    assert records
    for record in records:
        assert "\n" not in record.getMessage()
    text = "\n".join(record.getMessage() for record in records)
    assert "x" * 64 in text
    assert "x" * 65 not in text
    assert "forged: log line" not in text


def test_save_failure_log_does_not_leak_file_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = _make_store(tmp_path)

    def failing_replace(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failing_replace)
    with caplog.at_level(logging.WARNING, logger="barbaros.model_cache"):
        assert store.save({"top-secret-provider": [_model("sk-secret-token")]}) is False

    assert "sk-secret-token" not in caplog.text
    assert "top-secret-provider" not in caplog.text


# --- §4.2 limits: deterministic caps shared by load and save ----------------


def test_save_caps_providers_deterministically(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    providers = {f"p{i:04d}": [_model(f"m{i}")] for i in range(store.MAX_PROVIDERS + 1)}

    assert store.save(providers) is True
    loaded = store.load()
    assert len(loaded) == store.MAX_PROVIDERS
    assert list(loaded) == [f"p{i:04d}" for i in range(store.MAX_PROVIDERS)]


def test_load_caps_providers_deterministically(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    providers = {f"p{i:04d}": [_model(f"m{i}")] for i in range(store.MAX_PROVIDERS + 1)}
    _write_document(store.path, providers)  # bypasses save-side sanitizing

    loaded = store.load()
    assert len(loaded) == store.MAX_PROVIDERS
    assert f"p{store.MAX_PROVIDERS:04d}" not in loaded


def test_save_caps_models_per_provider_deterministically(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    models = [_model(f"m{i:05d}") for i in range(store.MAX_MODELS_PER_PROVIDER + 2)]

    assert store.save({"p": models}) is True
    loaded = store.load()
    assert len(loaded["p"]) == store.MAX_MODELS_PER_PROVIDER
    assert loaded["p"][0]["id"] == "m00000"
    assert loaded["p"][-1]["id"] == f"m{store.MAX_MODELS_PER_PROVIDER - 1:05d}"


def test_load_caps_models_per_provider_deterministically(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    models = [_model(f"m{i:05d}") for i in range(store.MAX_MODELS_PER_PROVIDER + 2)]
    _write_document(store.path, {"p": models})  # bypasses save-side sanitizing

    loaded = store.load()
    assert len(loaded["p"]) == store.MAX_MODELS_PER_PROVIDER
    assert loaded["p"][-1]["id"] == f"m{store.MAX_MODELS_PER_PROVIDER - 1:05d}"
