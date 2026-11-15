# BAR-11 — `NoKeyringError` is not handled — app crashes on start without Secret Service

- **Issue:** https://github.com/FRiMN/barbaros/issues/9
- **Label:** `security/owasp-finding`
- **Created:** 2026-11-09
- **Fixed:** 2026-11-15 (`02807ec`, `5cd5506`, `f0f0418`, `58768ac`, `574ef42`, `9873a20`, `3507c9d`, `9dbe372`, docstring-only `d699712`; tests `fa08e49` on `fix/bar-11-keyring-crash`; a separate docs-only commit on top records this finding/audit)
- **Status:** **fixed** for the system-keyring mode. The opt-in unencrypted-file mode is follow-up
  issue [#23](https://github.com/FRiMN/barbaros/issues/23) (accepted-risk finding, not implemented
  here).
- **Source:** `docs/security/owasp-audit.md` §3 finding BAR-11 (table §2; Top-10 mapping §7)
- **Related:** #8 (BAR-02 — API key lifecycle; same `security.py`, deletion and orphan-secret rules
  overlap with the storage changes below), [#23](https://github.com/FRiMN/barbaros/issues/23)
  (follow-up: opt-in unencrypted file store; supersedes the "no plaintext fallback" wording only by
  explicit, informed consent and is out of scope here)

## Issue body

## Summary

`NoKeyringError` is not handled. With no Secret Service available, `KeySecurityManager` raises and
the **application crashes on start** (through `ProvidersCard` construction reading keyring).

Source: `docs/security/owasp-audit.md` §3, finding **BAR-11**.

## OWASP classification

- Cheat Sheets: `Secrets_Management_Cheat_Sheet.md` §2.9; `Key_Management_Cheat_Sheet.md` →
  "Storage" (no plaintext fallback — that part is good).
- Top-10: **A04** Insecure Design, **A10:2025** Mishandling of Exceptional Conditions.

## Severity

**Low.**

## Location

- `security.py:7-25` (`get` at `:19`, `delete` at `:25`).
- `providers_card.py:30,132` (reads keyring while constructing the card).
- `provider_dialog.py:47,180`.

## Evidence

With `keyring.set_keyring(fail.Keyring())` the calls raise `NoKeyringError`; a real `App(...)`
crashes on start — traceback through `security.py:19` from `ProvidersCard` construction (default
`ollama`). In Flatpak access to `org.freedesktop.secrets` is declared, so the problem is unlikely
there.

## Recommendation

- Wrap the calls in `try/except keyring.errors.KeyringError`, return a typed result / `None`.
- On start check `keyring.get_keyring()` and show a non-blocking warning.
- Do not read keyring in the `ProvidersCard` constructor.
- In `delete()` catch `KeyringError`.
- **Do not** add a plaintext fallback.

## Discussion summary (2026-11-15)

The original recommendation fixes the crash but leaves a UX hole: a `Save` that keeps the key only
in process memory breaks the button's contract — the user discovers the loss on the next launch.
A silent memory fallback was therefore rejected as a design. The agreed direction is **explicit
storage modes**: the system keyring by default and an **opt-in unencrypted file** mode for systems
without Secret Service, with informed consent and a persistent UI indicator.

Options considered:

| Option | Verdict |
| --- | --- |
| Silent memory fallback | Rejected: breaks the `Save` contract, key disappears on exit. |
| Plaintext via `keyrings.alt` | Rejected: upstream calls it non-recommended; global `~/.local/share/python_keyring/keyring_pass.cfg` shared with other apps; non-atomic read-modify-write; follows symlinks; no size limits; `0600` only at creation. Also auto-selected silently when installed. |
| Custom `keyring` backend as the primary store | Rejected as the foundation (proven auto-selection and detection-cache problems below); may later be added as a thin, non-viable adapter over our file store if keyring API compatibility is wanted. |
| Own `SecretStorage` + `FileSecretStore` | **Chosen.** Full control over path, format, permissions, atomicity and error typing; no new dependency; reuses the already-audited `atomic_file` primitives. |

## Evidence from experiments (`.venv`, isolated `XDG_*`, fake/real keyring backends)

- `fail.Keyring`: `get_password`/`set_password`/`delete_password` all raise `NoKeyringError`
  (inherits `keyring.errors.KeyringError`).
- If the `SecretService` backend is selected and the D-Bus daemon/bus disappears at runtime,
  `secretstorage.dbus_init()` raises **`FileNotFoundError`**, i.e. not a `KeyringError`. Catching
  only `KeyringError` is not sufficient at this I/O boundary.
- `keyring.get_all_keyring()` is wrapped in `@once`. In a process where Secret Service was missing
  at first detection, restoring D-Bus and calling `keyring.core.init_backend()` keeps returning
  `fail.Keyring`; a retry without an app restart needs our own backend selection.
- Installing `keyrings.alt` makes `keyring.get_keyring()` return `PlaintextKeyring`
  (`priority 0.5` > `fail 0`) when no Secret Service is available: the plaintext fallback enables
  itself, without consent or indicator. Its file was created `0600`, but the directory stayed `775`;
  values are only base64-encoded.
- Importing a non-abstract `KeyringBackend` subclass with `priority = 10` makes it the selected
  backend **even with Secret Service available** (metaclass registry + priority selection; no entry
  point needed). Any custom backend must therefore be non-viable (`priority` classproperty raising
  `RuntimeError`) and be installed only through an explicit `keyring.set_keyring(...)`.
- `org.freedesktop.portal.Secret` does not remove the keyring dependency: in a typical backend the
  per-app master secret is itself stored in the user's keyring (portal documentation).

## Agreed design

The keyring-mode part of this design was implemented on 2026-11-15 (see **Implementation** below).
The opt-in unencrypted-file mode, consent UI, mode indicator and migration are **not** part of this
change: they are follow-up issue [#23](https://github.com/FRiMN/barbaros/issues/23). The text below
is kept as the agreed design, not as a description of the current diff.

### Storage

- `SecretStorage` facade with typed results: `FOUND` / `MISSING` / `LOCKED` / `UNAVAILABLE` /
  `CORRUPT`; `set`/`delete` return `PERSISTED` / `ERROR`. There is no silent session/memory store:
  the key is either persisted in the active store or the operation fails loudly.
- Two explicit modes, one active store at a time: **system keyring** (default) and **unencrypted
  file** (opt-in). No automatic fallback between them.
- File store: own `FileSecretStore` in `QStandardPaths.AppDataLocation` (same directory as the
  model cache; inside the Flatpak sandbox), file `0600`, directory `0700`, atomic write and
  symlink/FIFO/size protection via the existing `atomic_file` helpers, strict versioned JSON schema
  (`{"version":1,"keys":{provider:key}}`), byte/count limits, no secrets in `QSettings`, model cache
  or logs.
- Corrupt/unreadable/oversized file: fail-safe — never crash, never silently overwrite; keep a
  `0600` backup and start with a warning (same pattern as settings sanitization in BAR-01).
- Switching modes requires explicit consent and migration: keyring → file writes the file, verifies
  it, then removes keyring entries; file → keyring writes keyring entries, verifies by read-back,
  then removes the file. Failure aborts the switch and keeps the previous mode. No orphan secret in
  the inactive store.
- Plaintext mode is off by default; the consent dialog lists the risks (backups/sync, unencrypted
  disks at rest, same-uid processes, Flatpak apps with home access). A persistent "Unencrypted file
  storage active" indicator is shown in Settings/providers UI. No machine-id/TPM-style obfuscation:
  it would only hide plaintext behind a locally available key.

### Error handling

- Startup: probe for a usable backend; if unavailable, show a non-blocking banner (not a modal),
  the app still starts. `Retry` re-runs our own backend selection; `KeyringLocked` is retryable and
  is not the same as "no key".
- Explicit user actions (save/delete/read for a provider client): modal error and **abort the
  transaction** — the provider is not added/updated/removed and translation is not sent. The key is
  never included in the error text or logs; only the provider name (`%r`) and exception class.
- Catch broadly at the storage boundary (`KeyringError`, `SecretStorageException`, D-Bus/`OSError`),
  because of the `FileNotFoundError` evidence above.
- Remove keyring reads from widget constructors (`providers_card.py:132`); cards stop showing the
  masked key, the mask/status is only read from an explicit "Manage providers" action. This also
  avoids keyring unlock prompts and modal storms at startup.
- Deletion failures are surfaced, not swallowed; a provider is not removed while its secret could
  not be revoked (BAR-02 interplay).

### Composition

- Backend selection happens in the composition root (`main()`), before UI/worker threads; `App`
  receives the storage controller (tests keep using the autouse fake keyring fixture and do not run
  `main()`).
- No `keyrings.alt` dependency and no entry point for a custom backend. Reuse the existing
  `no_keyring` test fixture (`tests/conftest.py:128`).

## Scope split

1. **This issue (BAR-11):** storage facade + keyring error handling + crash fix + typed statuses +
   banner/dialogs + no constructor reads + tests with `fail.Keyring`. No file mode.
   **Implemented** (commits `02807ec`, `5cd5506`, `f0f0418`, `58768ac`, `574ef42`, `9873a20`, `3507c9d`, `9dbe372`; docstring-only `d699712`; tests `fa08e49`).
2. **Follow-up issue:** unencrypted file mode + consent UI + mode indicator + migrations + tests —
   [#23](https://github.com/FRiMN/barbaros/issues/23).
3. **Docs:** updated `docs/security/owasp-audit.md` (BAR-11 status/residual risk; the stale
   "plaintext fallback absent" statements in §5/§6 and plan item §9/§10) — done in this change.

## Implementation (2026-11-15)

Architecture/design write-up: [`docs/secret-storage.md`](../../docs/secret-storage.md); interactive diagram: [`docs/diagrams/secret-storage.html`](../../docs/diagrams/secret-storage.html).

Commits: `02807ec` (typed boundary, no startup reads), `5cd5506` (backend vetting gates every
operation), `f0f0418` (fail-safe backend inspection), `58768ac` (chainer matched without importing
it; empty chainer refused), `574ef42` (chainer recognised through its MRO, including subclasses),
`9873a20` (keyless providers stay usable while the store is down), `3507c9d` (any keyless-client
creation failure is mapped back to the typed storage error), `9dbe372` (keyless probing limited to
`KEYLESS_PROVIDER_TYPES`; cloud providers fail fast), `d699712` (docstring-only: runtime error
texts stay English, only status labels are translated), test-only `fa08e49`. No new dependency
(`keyring.backends.chainer` ships with `keyring`); `import barbaros.security` and constructing the
store/facade are side-effect-free (verified: 0 `get_keyring`/`set_keyring`/`init_backend` calls).

### `src/barbaros/security.py` (the boundary)

- **Typed results, no exceptions to the UI.** `SecretStatus` (`FOUND`, `MISSING`, `LOCKED`,
  `UNAVAILABLE`, `CORRUPT`), `WriteStatus` (`PERSISTED`, `ERROR`), `Availability` (`READY`,
  `UNAVAILABLE`), immutable `SecretRead(status, value, reason)` and the `SecretStore` Protocol.
  `LOCKED` is retryable and is *not* "no key"; `CORRUPT` covers non-text, empty, over-limit
  (`MAX_SECRET_LEN = 16 KiB`) and non-UTF-8-encodable (lone surrogate) entries.
- **`KeyringSecretStore` maps the whole I/O boundary.** Reads: `KeyringLocked` → `LOCKED`,
  `UnicodeDecodeError` → `CORRUPT`, any other `Exception` → `UNAVAILABLE`; writes/deletes:
  `PERSISTED`/`ERROR`, `PasswordDeleteError` on delete is success (idempotent). The mapping is
  broader than `keyring.errors.KeyringError` on purpose: a dead D-Bus session raises
  `FileNotFoundError` from `secretstorage`, and `BaseException` (`KeyboardInterrupt`) deliberately
  escapes. Failures log only the provider name (`repr`, truncated to 64 chars) and the exception
  **class name** — never `str(exc)`, a decoded value or the secret.
- **Backend vetting gates every operation.** `_usable_backend()` is shared by `availability()`,
  `read()`, `write()` and `delete()`: `keyring.backends.fail` (no backend), `keyring.backends.null`
  (reads return nothing, writes are discarded), any `keyrings.alt` backend (class **MRO** match, so
  a subclass defined outside the package is caught too) and a `ChainerBackend` wrapping one are
  refused → `UNAVAILABLE`/`ERROR`, with a WARNING. The chainer is matched through its **MRO** but
  **without importing it** (a subclass defined outside `keyring.backends.chainer` inherits the
  write-through behaviour and is refused too; importing the module would register the class in
  keyring's global backend registry and could change keyring's own selection); an empty chainer
  would silently drop writes and is refused too (`chained-empty`). This is what keeps "no plaintext without
  explicit consent" true on the save path, not only in the banner. The operation uses the vetted
  backend instance, so a concurrent backend swap cannot route a vetted call elsewhere; a backend
  inspection that raises is itself a refusal (`inspection-failed`), never a crash.
- **Retry re-detects.** `_reset_backend_detection()` resets keyring's cached backend detection
  (`get_all_keyring.reset()`) and re-runs `init_backend()`; `reset()` raising `KeyError` (detection
  cache never populated, e.g. after an explicit `keyring.set_keyring(...)`) is expected and does not
  skip re-detection; a failing re-detection is logged, never raised.
- **Facade validation.** `SecretStorage` checks the provider name (non-empty `str`, ≤256 chars) and
  the secret (non-empty `str`, ≤16 KiB, UTF-8-encodable) and returns `MISSING`/`ERROR` with a
  WARNING for invalid input — no exception into the GUI. There is deliberately **no in-memory
  session store and no fallback**: the key is either persisted in the active store or the operation
  fails loudly (`WriteStatus.ERROR` / `SecretStorageError`).
- **`ApiKeyManager`** binds one provider to the app-selected `SecretStorage`; `value()` returns the
  key, `None` only for `MISSING`, and raises a typed `SecretStorageError` (static user-facing
  message, no secret) for `LOCKED`/`UNAVAILABLE`/`CORRUPT` so callers abort instead of treating a
  storage failure as "no key".

### Wiring (composition root)

- `src/barbaros/main.py`: `main()` selects the store before any UI/worker exists —
  `SecretStorage(KeyringSecretStore())` — and passes it through `start_app()` → `App(secrets=...)`.
- `src/barbaros/main_window.py`: `MainWindow(app=..., secrets=...)` passes it to `ModelManager`.
- `src/barbaros/model_manager.py`: `ProviderMeta.__post_init__` creates an unbound `ApiKeyManager`
  (no I/O); `ModelManager(secrets=...)` exposes `secret_storage`; `add()` binds the provider's
  manager to the app store **before** the client (which reads the key) is created;
  `ProviderClient.client()` uses `api_key_manager.value()` and, when the store cannot tell whether a
  key exists, tries a keyless client **only for the explicit local set** `KEYLESS_PROVIDER_TYPES`
  (`ollama`, `llamacpp`, `llamafile`, `lmstudio`, `vllm`), matching the banner ("keyless providers
  keep working"). A cloud provider is not probed keyless — that constructor is slow and
  side-effectful (AWS credential chain, Google ADC discovery) — it gets the typed
  `SecretStorageError` immediately (fail fast, no GUI freeze). Any keyless creation failure is
  mapped back to the typed storage error (`3507c9d`). A batch fetch catches `SecretStorageError` and
  reports it through the existing `error` signal; `ListModelWorker` is now built before its
  `QThread`, so a storage failure leaves no half-created thread behind.
- `src/barbaros/widgets/providers_card.py`: the card **no longer reads keys** (the masked-key label
  is gone). When `availability()` is not `READY`, a non-blocking warning row with a `Retry` button
  is shown; `Retry` re-probes with `refresh=True`. The app starts and stays usable; keyless
  providers can still fetch models.
- `src/barbaros/widgets/provider_dialog.py`: `ProviderDialog` shows a masked key for `FOUND`, an
  empty cell for `MISSING` and the typed status (`unavailable`/`locked`/`corrupt`) otherwise, plus
  a non-blocking warning if any read failed. `AddProviderDialog` reads the key only when opened for
  an explicit edit (empty field + inline warning on failure); `get_provider()` performs no I/O.
  Saving a key is a transaction step: write first, and on `ERROR` show a modal error and **abort**
  the provider add/update (table and settings untouched).
- `src/barbaros/features/text.py`, `src/barbaros/features/ocr.py`: the worker is built inside
  `try`/`except SecretStorageError`; for a cloud/key-requiring provider a storage failure shows the
  normal error dialog, restores the tab (buttons/progress reset) and nothing is sent (translation
  text, OCR image). A local keyless provider keeps working on the degraded path (keyless client,
  no secret read).
- `src/barbaros/widgets/secret_storage_ui.py` + `src/barbaros/i18n/barbaros_ru.ts/.qm`: translated
  short status labels and hints for `LOCKED`/`UNAVAILABLE`/`CORRUPT`; no new secret-bearing strings.

### What was verified (not assumed)

- `fail.Keyring`: the app (`MainWindow`) starts; **0** `get_password` calls during startup; a
  non-blocking banner and a working `Retry`; explicit key operations return typed statuses and the
  add/update transaction aborts; no traceback in the user-facing path.
- Keyless providers on an unavailable store: `ollama`/`lmstudio` → a keyless client is built and the
  request can proceed without a key; `openai`/`otari`/`vertexai`/`bedrock` → `AnyLLM.create` is not
  called at all (verified with a call counter) and the typed `SecretStorageError` is raised
  immediately, so translation/OCR abort before sending and the GUI does not freeze on cloud
  credential discovery. No key is read in any case, so no secret can leak on this path.
- Vetting: `null`/`fail`/`keyrings.alt`-module/`ChainerBackend`-wrapping-alt → `UNAVAILABLE` +
  `ERROR`; nothing is written by the app. Pinned by
  `tests/unit/test_secret_storage.py::test_refused_backend_cannot_be_used_for_any_operation`
  (fail/null/subclasses/chainer subclass with a plaintext member/empty chainer). Repro during
  implementation review: a fake backend with
  `type(backend).__module__ = "keyrings.alt.file"` → `availability()=UNAVAILABLE`, `write()=ERROR`,
  nothing stored; `null.Keyring` → `write()=ERROR` with an empty store; a chainer wrapping such a
  backend → `UNAVAILABLE`. This was the gap fixed in `5cd5506`/`f0f0418`/`58768ac`/`574ef42`: on
  `02807ec` the vetting only gated `availability()`, so `null` reported `PERSISTED` while discarding
  the secret and a plaintext-alternative backend received the value.
- Boundary mapping matrix (experimenter evidence, unchanged by the vetting commit):
  `NoKeyringError`/`FileNotFoundError`/`OSError`/arbitrary `Exception` → `UNAVAILABLE`,
  `KeyringLocked` → `LOCKED`, `UnicodeDecodeError` → `CORRUPT`, `PasswordDeleteError` on delete →
  `PERSISTED` (idempotent), `KeyboardInterrupt` escapes.
- Secret hygiene: the secret never appears in logs, `SecretRead.reason`, error dialogs or
  `ProviderMeta.schema().dump()`; the providers table shows only `truncate_key()` output; the
  aborted transaction leaves neither a provider nor the key persisted.
- Guard combinations: no new dependency; `pyproject.toml`/`uv.lock` unchanged.

## Audit/process impact

- **This change:** the keyring mode keeps "no plaintext fallback" intact and now enforces it at the
  storage boundary (vetting on every operation). The PR needs the usual OWASP pass, a comment trail
  and the `security/owasp-passed` label on the final diff (AGENTS.md #27), plus a "Trade-offs /
  residual risk" section in the PR body. The label applies to this diff only; a later commit that
  changes the security surface re-opens the review.
- **Follow-up [#23](https://github.com/FRiMN/barbaros/issues/23):** the opt-in plaintext mode
  supersedes this issue's "Do not add a plaintext fallback": it becomes an explicit,
  user-accepted risk, recorded as an accepted-risk finding (`security/owasp-finding`) with the
  audit document updated for that mode.
- Residual risks of file mode (out of scope here, recorded for #23): copies in backups/sync,
  unencrypted disk at rest, same-uid processes (the project's threat model already treats same-uid
  as trusted, BAR-10), and Flatpak apps with home access. Keyring itself is not an app-isolation
  boundary once the session is unlocked.

## Tests

Implemented on `fix/bar-11-keyring-crash` (added by the test-authoring commit):

- `tests/unit/test_secret_storage.py` — contract of the typed boundary: `fail`/`null`/`alt`/regular
  backends; read mapping (`LOCKED`, `UnicodeDecodeError`/non-text/oversized → `CORRUPT`,
  `FileNotFoundError`/`OSError`/arbitrary exceptions → `UNAVAILABLE`); write/delete statuses and
  idempotent delete; **the secret never reaches logs or `reason`**; backend vetting (refused on
  availability and on the write path — including the `keyrings.alt`/chainer cases); Retry
  re-detection and its fail-safety; facade validation (provider name / secret limits, invalid input
  never reaches the boundary and is never logged); `ApiKeyManager` lazy default store and `bind()`.
- `tests/components/test_provider_client_storage.py` — `ProviderClient.client()` key handling: a
  keyless provider on an unavailable store gets a keyless client; a cloud/key-requiring provider
  gets the typed `SecretStorageError`, any keyless-creation failure is mapped to it, no secret value
  is ever passed to the client on the degraded path.
- `tests/system/test_keyring_unavailable.py` — real `MainWindow` on `fail.Keyring`: **no key read at
  startup**, non-blocking banner + working Retry; explicit `ProviderDialog` read shows a typed
  status; add-provider transaction aborts (no provider, no settings write, no secret in dialogs) and
  a working store persists + masks the key; edit-prefill failure warning; translation and OCR abort
  before sending and restore the tab for a cloud provider, while a keyless local provider keeps
  working; model fetch reports a storage error through the existing error signal instead of raising;
  the secret never reaches disk/`QSettings`/the model cache/logs.
- Existing security tests updated for the moved premise: the startup read in `ProvidersCard` is
  gone, so the "secret never reaches cache bytes/logs" assertion now exercises an explicit dialog
  action (`tests/system/test_model_cache_security.py`).
- Full suite: `615 passed, 3 deselected` (`./.venv/bin/python -m pytest -q`, ~54 s; +102 tests vs
  `main`); `./.venv/bin/python -m ruff check src tests` → `All checks passed!`.

The following test items from the original list belong to the follow-up mode and are **not** covered
here: file-mode round-trip/`0600`/`0700`/atomic write/corrupt/symlink/FIFO/oversized, consent UI,
mode indicator, migration both directions, no duplicate/stale secret in the inactive store
([#23](https://github.com/FRiMN/barbaros/issues/23)).

## Residual risk / trade-offs

- **`availability()` is a capability probe, not a liveness check.** It answers "may this backend
  class be used", not "will the next call succeed". If the Secret Service/D-Bus session dies after
  the probe, `availability()` can keep returning `READY` until the next refresh/restart while
  `read()` returns `UNAVAILABLE(FileNotFoundError)`; the banner then appears after a refresh, and
  the explicit dialog/save paths already show the typed error. This avoids keyring I/O in UI
  constructors at the cost of a slightly stale banner.
- **Refused *selected* backend → keyring storage is refused entirely (fail-closed).** This happens
  when the selected backend is the plaintext backend from `keyrings.alt` directly (no Secret Service),
  **or a `ChainerBackend` that includes it — even when a working Secret Service is present**: with two
  or more positive-priority backends keyring selects the chainer (priority 10), and the app refuses it
  as `chained-plaintext-alternative` rather than risk a silent plaintext store. This is deliberate; the
  remedy is to remove `keyrings.alt`. The opt-in file store (#23) is the intended explicit
  alternative.
- **Keyless fallback failures map back to the typed error (review finding, fixed in `3507c9d`).**
  Whenever a keyless client is attempted (the local types only, `9dbe372`), any creation failure
  (`MissingApiKeyError`, `ValueError` for a missing `api_base`, missing cloud credentials, ...) is
  re-raised as the original typed `SecretStorageError` (`except Exception`, so `BaseException` /
  `KeyboardInterrupt` still escapes). Verified on the frozen tree: `ollama`/`lmstudio` → keyless
  client; `openai`/`otari` without `api_base`/`vertexai` without ADC → `SecretStorageError(UNAVAILABLE)`
  with **no** `AnyLLM.create` call for the cloud types; `KeyboardInterrupt` propagates.
- **Keyring calls block the GUI thread** for their duration (existing behaviour of the keyring
  library; measured: 0 event-loop ticks during a 250 ms backend call). The change does not move key
  I/O to a worker; it removes the *startup* read, which is the freeze that mattered for the crash
  scenario. A hung D-Bus call can still freeze the GUI for its duration when the user opens the
  providers dialog.
- **The keyless allowlist is hardcoded.** `KEYLESS_PROVIDER_TYPES` = ollama/llamacpp/llamafile/
  lmstudio/vllm. A local OpenAI-compatible endpoint configured with the `openai` provider type fails
  closed while the keyring is down (it is treated as a cloud provider); the remedy is to use a local
  provider type or restore the keyring. The set needs updating when new local provider types are
  added.
- **Local keyless client construction is not free on the degraded path:** ~35–185 ms per type
  (reviewer measurements), in the GUI thread on an explicit action. This is the deliberate trade-off
  against cloud providers, whose keyless constructors cost 2.2–12.5 s (AWS credential chain / Google
  ADC) and are therefore not attempted at all.
- **Provider-config errors are masked while the store is down.** `_client_without_key()` (`3507c9d`)
  maps any keyless-client creation failure to the typed `SecretStorageError`, so a genuine provider
  configuration error (e.g. a missing `api_base`) is not reported in that state; with a working store
  it is reported as before. Deliberate: the degraded path must report secrets availability, not
  configuration.
- **Runtime error wording stays English.** `SecretStorageError`/`_USER_MESSAGES` are English like the
  other runtime errors; only the short widget status labels/hints are translated
  (`secret_storage_ui.py`, `barbaros_ru.ts/.qm`). Known i18n debt, unchanged behaviour of this PR.
- **Vetting is a class-based denylist heuristic, not a sandbox.** It refuses the known-bad backends
  (fail/null/keyrings.alt, including subclasses via MRO and chainer members) and degrades to
  "not usable" when inspection raises, but (F3) a **delegating wrapper** that forwards to a refused
  backend without being a `ChainerBackend`/`keyrings.alt` subclass is not recognised, and code that
  runs in the same process can call `keyring.set_keyring(...)` or register an arbitrary backend.
  Defending against arbitrary in-process code is outside the audit threat model
  (same-uid/compromised process is already trusted for keyring access, BAR-10); this is a defense
  against *accidental/silent* plaintext fallback, not app isolation.
- **Chainer inspection cost per operation (F9).** When a `ChainerBackend` is selected, vetting walks
  its wrapped backends and evaluates their priorities on **every** `read`/`write`/`delete` (and every
  row the providers dialog reads), which can repeat D-Bus availability probes; there is no cached
  verdict because the backend can change in-process. In the common configurations the chainer is
  either refused (when `keyrings.alt` is present) or not selected at all (single backend), so the
  cost is limited to the chainer case.
- **`secretstorage.LockedException`** (a race inside `item.get_secret()` of the Secret Service
  backend) maps to `UNAVAILABLE`, not `LOCKED`, because the contract maps only
  `keyring.errors.KeyringLocked` to `LOCKED`. The wording may therefore say "unavailable" for a
  briefly locked collection; retrying still works.
- **Key lifecycle is still BAR-02 (#8):** `ApiKeyManager.delete()` exists and is typed, but the app
  does not call it on provider removal ("delete saved key" is out of scope here). `SERVICE_NAME` is
  unchanged, so keys saved by older versions stay readable.
