"""Security tests for the JSON model cache.

Covers docs/model-cache-storage.md §7.2, "Security — tests/system/
test_model_cache_security.py", items 1-5, plus the BAR-19 write guard (item 6,
also listed in docs/security/owasp-audit.md §10).  Item 6 of the storage plan
(cached ``model.id`` rendered as HTML) is deliberately out of scope for this
refactoring: it belongs to BAR-13.

The cache file is untrusted input: it may be replaced by another process and
may carry fields the application never asked for.  These are system tests
through ``MainWindow`` because that is the real composition root; the store and
the manager get their own unit/component tests elsewhere.

Explicitly *not* asserted here: BAR-01 is not fixed by this refactoring.  The
cache file itself is plain JSON, so it must simply never contain pickle markers
- the pickled ``main_window/model``/``ocr_feature/model`` keys are still there
and are a separate P0.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
from pathlib import Path

import pytest
from any_llm.types.model import Model

import barbaros.model_manager
from barbaros.main_window import MainWindow
from barbaros.model_cache import SETTINGS_KEY, ModelCacheDocument, ModelCacheStore

POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix", reason="file permission bits are POSIX-only"
)

# Representations of a Qt/pickle-serialized object; the cache must stay plain
# JSON (BAR-01 is a different task, but no new serialization format may creep
# in here).
FORBIDDEN_BYTE_MARKERS = (b"PyObjectWrapper", b"@Variant", b"pickle")

KEYRING_SERVICE = "barbaros:providers_api_keys"


# --- helpers ---------------------------------------------------------------


def cache_file(data_home) -> Path:
    """Default cache location for a redirected ``XDG_DATA_HOME``."""
    return data_home / "barbaros" / "models.json"


def model_entry(model_id: str, **extra: object) -> dict:
    """One cache entry in the allowlisted shape, plus deliberately extra keys."""
    entry: dict = {
        "id": model_id,
        "created": 1_710_000_000,
        "object": "model",
        "owned_by": "tester",
    }
    entry.update(extra)
    return entry


def allowlisted_model() -> Model:
    """A model as any_llm would hand it over after a fetch."""
    return Model.model_validate(
        {
            "id": "fetched-1",
            "created": 1_710_000_100,
            "object": "model",
            "owned_by": "tester",
        },
        strict=True,
    )


@contextlib.contextmanager
def open_window(fake_app):
    """Build ``MainWindow`` and always shut its threads down afterwards."""
    window = MainWindow(app=fake_app)
    try:
        yield window
    finally:
        window.model_manager.shutdown()
        window.deleteLater()


def raw_cache_bytes(path: Path) -> bytes:
    return path.read_bytes()


# --- 1. saved bytes are plain sanitized JSON --------------------------------


def test_saved_cache_has_only_allowlisted_json_fields(
    data_home, fake_app, write_cache, cache_doc
):
    """A save writes valid UTF-8 JSON whose model objects contain only §4.2 keys.

    The substituted cache file carries extra model fields (``api_base``,
    ``api_key``, ``evil``); so does a model object passed to ``set_models``
    (upstream endpoints are free to add fields).  Neither may survive into the
    saved file or into the data read back from it.
    """
    path = cache_file(data_home)
    write_cache(
        path,
        cache_doc(
            {
                "ollama": [
                    model_entry("cached-1", api_base="http://evil.invalid"),
                    model_entry(
                        "cached-2",
                        api_key="sk-cached-secret",
                        evil={"nested": True},
                    ),
                ]
            }
        ),
    )
    # The substituted file really did carry the extra fields we want stripped.
    substituted = raw_cache_bytes(path)
    assert b"api_base" in substituted
    assert b"api_key" in substituted
    assert b"evil" in substituted

    tainted_model = Model.model_validate(
        {
            **model_entry(
                "fetched-1",
                api_base="http://evil.invalid",
                api_key="sk-fetched-secret",
                evil=True,
            )
        },
        strict=True,
    )

    with open_window(fake_app) as window:
        restored = list(window.model_manager["ollama"].models)
        assert [model.id for model in restored] == ["cached-1", "cached-2"]
        window.model_manager.set_models("ollama", [*restored, tainted_model])

    raw = raw_cache_bytes(path)
    document = json.loads(raw.decode("utf-8"))

    assert set(document) == {"version", "models"}
    assert document["version"] == ModelCacheDocument.VERSION
    assert list(document["models"]) == ["ollama"]
    entries = document["models"]["ollama"]
    assert [entry["id"] for entry in entries] == ["cached-1", "cached-2", "fetched-1"]
    allowed_keys = set(ModelCacheDocument.ALLOWED_MODEL_KEYS)
    for entry in entries:
        assert set(entry) == allowed_keys

    for marker in (*FORBIDDEN_BYTE_MARKERS, b"api_base", b"api_key", b"evil"):
        assert marker not in raw, marker

    # Reading the written file back through the store returns exactly what the
    # JSON contains: no extra fields are resurrected by sanitization.
    assert ModelCacheStore(path).load() == document["models"]


# --- 2. API key stays in the keyring ----------------------------------------


def test_api_key_never_appears_in_cache_bytes_or_logs(
    data_home,
    fake_app,
    fake_keyring,
    write_cache,
    cache_doc,
    make_models,
    caplog,
    monkeypatch,
):
    """A keyring secret never reaches the cache file or the cache loggers.

    The whole run is covered: cache load, startup restore and the
    ``set_models``/save path all happen inside the captured log scope.
    """
    secret = "sk-test-DO-NOT-LEAK-0123456789"
    fake_keyring.set_password(KEYRING_SERVICE, "ollama", secret)
    assert fake_keyring.get_password(KEYRING_SERVICE, "ollama") == secret

    key_lookups: list[str | None] = []
    original_get_password = fake_keyring.get_password

    def recording_get_password(service, username):
        value = original_get_password(service, username)
        key_lookups.append(value)
        return value

    monkeypatch.setattr(fake_keyring, "get_password", recording_get_password)

    path = cache_file(data_home)
    # One invalid entry makes the store log on its DEBUG "skipped" path, so
    # the assertion below is not made against an empty capture.  Two valid
    # entries are restored on startup.
    invalid_entry = {
        "id": "",
        "created": 1_710_000_000,
        "object": "model",
        "owned_by": "tester",
    }
    write_cache(path, cache_doc({"ollama": [*make_models(2), invalid_entry]}))

    with (
        caplog.at_level(logging.DEBUG, logger="barbaros.model_cache"),
        caplog.at_level(logging.DEBUG, logger="barbaros.model_manager"),
        open_window(fake_app) as window,
    ):
        # Both loggers are captured at DEBUG for this run (load, restore, save).
        assert logging.getLogger("barbaros.model_manager").isEnabledFor(logging.DEBUG)
        window.model_manager.set_models("ollama", [allowlisted_model()])

    # The secret really was read by the app during startup (ProvidersCard), yet
    # the capture is live and contains no trace of it.
    assert secret in key_lookups
    assert any(record.name == "barbaros.model_cache" for record in caplog.records)

    raw = raw_cache_bytes(path)
    raw.decode("utf-8")  # the cache is textual, so the key must be absent as text
    assert secret.encode() not in raw
    assert secret not in caplog.text


# --- 3. private file mode ---------------------------------------------------


@POSIX_ONLY
def test_cache_file_and_directory_are_private(data_home, fake_app):
    """The cache file is ``0600`` and its directory ``0700`` after a save."""
    with open_window(fake_app) as window:
        window.model_manager.set_models("ollama", [allowlisted_model()])

    path = cache_file(data_home)
    file_mode = stat.S_IMODE(path.stat().st_mode)
    directory_mode = stat.S_IMODE(path.parent.stat().st_mode)
    assert file_mode == 0o600, oct(file_mode)
    assert directory_mode == 0o700, oct(directory_mode)


# --- 4. unknown provider in a substituted cache -----------------------------


def test_unknown_cached_provider_adds_nothing(
    data_home,
    fake_app,
    fake_settings,
    fake_keyring,
    write_cache,
    cache_doc,
    make_models,
    monkeypatch,
):
    """A cache entry for ``evil`` cannot add a provider, config, key or client."""
    providers_config = [{"name": "ollama", "provider_type": "ollama", "api_base": None}]
    fake_settings.setValue("main_window/llm_providers", json.dumps(providers_config))
    config_before = fake_settings.value("main_window/llm_providers")

    write_cache(
        cache_file(data_home),
        cache_doc(
            {
                "ollama": make_models(1),
                "evil": [
                    model_entry(
                        "evil-model",
                        api_base="http://attacker.invalid",
                        api_key="sk-evil",
                    )
                ],
            }
        ),
    )

    client_creations: list[tuple] = []

    def record_create(*args, **kwargs):
        client_creations.append((args, kwargs))
        raise AssertionError("no network client may be created from the cache")

    monkeypatch.setattr(barbaros.model_manager.AnyLLM, "create", record_create)

    with open_window(fake_app) as window:
        assert list(window.model_manager) == ["ollama"]
        assert "evil" not in window.model_manager

    assert client_creations == []
    assert fake_settings.value("main_window/llm_providers") == config_before
    assert "evil" not in str(fake_settings.value("main_window/llm_providers"))
    assert fake_keyring.passwords == {}


# --- 5. log injection through an external provider name ---------------------


def test_log_injection_provider_name_is_escaped_on_one_line(
    data_home, fake_app, write_cache, cache_doc, caplog
):
    """A newline/HTML provider name cannot forge an extra log record.

    The cache entry is corrupt on purpose (``models`` is a string, not a list)
    so the store logs the provider name on its "skipped" path.
    """
    payload = "evil\nFAKE LOG <script>x</script>"
    write_cache(cache_file(data_home), cache_doc({payload: "not-a-list"}))

    with (
        caplog.at_level(logging.DEBUG, logger="barbaros.model_cache"),
        open_window(fake_app),
    ):
        pass

    skipped = [
        record
        for record in caplog.records
        if record.name == "barbaros.model_cache"
        and "skipped provider" in record.getMessage()
    ]
    assert len(skipped) == 1
    message = skipped[0].getMessage()

    escaped = repr(payload)
    assert escaped in message
    assert payload not in message
    assert "\n" not in message
    assert message.count("evil") == 1

    # No record (at any logger) contains the unescaped injected payload, and
    # the payload text itself produced a single record.
    assert all(payload not in record.getMessage() for record in caplog.records)
    assert sum("FAKE LOG" in record.getMessage() for record in caplog.records) == 1


# --- 6. BAR-19: model_cache_path is not an arbitrary write sink -------------


def test_configured_foreign_file_is_never_overwritten(
    tmp_path, data_home, fake_app, fake_settings
):
    """A ``model_cache_path`` pointing at someone else's file is refused.

    This is the user-visible end of BAR-19: before the write guard, the first
    ``set_models`` atomically replaced the configured file with cache JSON.
    """
    victim = tmp_path / "important.conf"
    victim_bytes = b"IMPORTANT USER DATA\n"
    victim.write_bytes(victim_bytes)
    os.chmod(victim, 0o644)
    fake_settings.setValue(SETTINGS_KEY, str(victim))
    fake_settings.sync()

    with open_window(fake_app) as window:
        window.model_manager.set_models("ollama", [allowlisted_model()])

    assert victim.read_bytes() == victim_bytes
    assert stat.S_IMODE(victim.stat().st_mode) == 0o644
    assert list(tmp_path.glob(".barbaros-*.tmp")) == []
    # The refused write did not fall back to the default location either.
    assert not cache_file(data_home).exists()


def test_foreign_file_at_the_default_cache_path_is_never_overwritten(
    data_home, fake_app
):
    """The guard also protects the auto-resolved location, not only overrides."""
    victim = cache_file(data_home)
    victim.parent.mkdir(parents=True)
    victim_bytes = b"IMPORTANT USER DATA\n"
    victim.write_bytes(victim_bytes)
    os.chmod(victim, 0o644)

    with open_window(fake_app) as window:
        window.model_manager.set_models("ollama", [allowlisted_model()])

    assert victim.read_bytes() == victim_bytes
    assert stat.S_IMODE(victim.stat().st_mode) == 0o644
    assert [entry.name for entry in victim.parent.iterdir()] == ["models.json"]
