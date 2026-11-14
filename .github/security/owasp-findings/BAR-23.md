# BAR-23 — `terminate()` + `wait()` without timeout and no network timeouts → GUI hang

- **Issue:** https://github.com/FRiMN/barbaros/issues/10
- **Label:** `security/owasp-finding`
- **Created:** 2026-11-09
- **Fixed:** 2026-11-13
- **Source:** `docs/security/owasp-audit.md` §4 finding BAR-23 (table §2; Top-10 mapping §7)
- **Related:** #12 (BAR-26 — `aboutToQuit.connect(cleanup)` lives inside `save_language`, so a normal
  quit may not call `shutdown()` at all; not fixed here, but the exit half of this finding only
  manifests through that path). BAR-24 in `docs/security/owasp-audit.md` §4 (unbounded `list_models`
  response; no separate GitHub issue yet) — response size limits are *not* part of this fix.

## Issue body

## Summary

`QThread.terminate()` followed by `wait()` **without a timeout**, plus no network timeouts, hangs
the GUI when stopping a fetch or exiting the application.

Source: `docs/security/owasp-audit.md` §4, finding **BAR-23**.

## OWASP classification

- Cheat Sheets: `Denial_of_Service_Cheat_Sheet.md` §Application attacks → "Handle exceptions",
  "Threading"; `Secure_AI_Model_Ops_Cheat_Sheet.md` §4 Inference API Security (limits / kill
  switches).
- Top-10: **A10:2025** Mishandling of Exceptional Conditions (2021: A04).

## Severity

**Low.**

## Location

- `model_manager.py:185-201` — `stop_fetching_models`: `thread.terminate()` (`:198`) +
  `thread.wait()` **without an argument** (`:199`); called from `remove()` (`:152-157`),
  `shutdown()` (`:178-183`, on `aboutToQuit`), `_start_fetching_models` (`:218`).
- `workers.py:121-142` — synchronous `client.list_models()` without a timeout.

## Evidence (reproduced)

- A thread in a Python loop (typical for marshalling, `workers.py:128-136`): `terminate()` returns
  instantly, then `wait(2000)` did not return in >20 s (process killed by timeout); Qt docs for
  `QThread::terminate()` warn that the thread may not terminate.
- Control: a thread in C `sleep(60)` is terminated by terminate in 0.001 s.
- The application sets no network timeouts: `AnyLLM` defaults to `Timeout(connect=5, read=600,
  write=600, pool=600)` — an endpoint can hold the read for up to 10 minutes.

## Scenario

A compromised / fake endpoint returns a "slow" or huge model list; the user clicks Reload / removes
a provider / closes the app → the GUI enters `wait()` and hangs (in the degenerate case —
indefinitely); on exit the application does not close.

## Impact

Availability (GUI hang, inability to quit), potentially interpreter state corruption from
`terminate()` (Qt: "dangerous and its use is discouraged").

## Recommendation

- Do not use `terminate()`: cooperative cancellation (`QThread.requestInterruption()` + a flag in
  the loop; for HTTP — an asyncio task / timeout), `wait(ms)` with a timeout and logging.
- Explicit connect / read / total timeouts and a size limit on the `list_models` response.
- `shutdown()` must not block the GUI longer than N ms.
- Test: NFR "stop/shutdown with a hung fake provider returns < 2 s, the app closes"; unit "wait is
  called with a timeout".

## Resolution

1. **Cooperative cancellation instead of `terminate()`.** `ListModelWorker.run()` now creates its
   own asyncio event loop in its `QThread` and runs the provider request as a task. `cancel()` is
   thread-safe and idempotent (flag under a lock + `loop.call_soon_threadsafe(task.cancel)`); it
   works before `run()` started (the request is not made at all), during the request (the task is
   cancelled and the in-flight HTTP request is aborted) and after completion (no-op). For providers
   that bridge a synchronous SDK through `asyncio.to_thread` (e.g. bedrock) the awaiting coroutine
   is cancelled and the worker thread finishes, although the SDK call itself may run to completion
   in a background executor thread.
2. **App-level total request deadline.** `LIST_MODELS_TIMEOUT_S = 20.0` bounds the whole
   `await client.alist_models()` through `asyncio.wait_for`. This is provider-independent:
   `any_llm` has no portable per-request `timeout` for `alist_models` (some providers reject the
   keyword), so a client-level connect/read-timeout injection was deliberately not attempted. On
   timeout exactly one `error` is emitted (`list_models timeout after <N>s`); `finished` is not.
3. **Bounded stop and stale-result guard.** `ModelManager.stop_fetching_models()` calls
   `worker.cancel()` and then `thread.wait(STOP_WAIT_MS = 1000)`; `QThread.terminate()` is never
   called. If the thread does not stop within the budget, a WARNING is logged (provider name
   through `_short_repr`, no exception text, URL or key) and the GUI continues. A result or an
   error of a stopped fetch is never applied: the result dispatcher is created per fetch, keeps a
   Python reference to its worker, and `_apply_worker_result()`/`_apply_worker_error()` check it
   against the provider's currently tracked worker (no entry or a different worker → DEBUG and
   drop). This closes the Reload/remove
   race where a `finished` queued before `cancel()` would overwrite the newer list; a `sender()` or
   disconnect-based guard does not work because Qt may already have deleted the worker's C++ object
   when the queued delivery runs. A thread that ignored the budget stays referenced in
   `_retiring_workers` until it is destroyed — destroying a running `QThread` aborts the process.
4. **Bounded shutdown.** `shutdown()` cancels every fetch worker under one shared deadline
   (`SHUTDOWN_BUDGET_MS = 1500`, below the issue's "< 2 s" NFR) and is idempotent. A batch reload of
   all providers uses the same shared deadline instead of N × `STOP_WAIT_MS`. Workers already left
   running past an earlier stop budget are reported in the shutdown WARNING (they are not awaited
   again).
5. **Deterministic thread exit.** `connect_terminate()` connects `thread.quit` with
   `Qt.ConnectionType.DirectConnection`: while the GUI thread is blocked inside `wait()`, its event
   queue is not processed and a queued connection would not stop the thread. A new terminal
   `stopped()` signal is emitted from `run()`'s `finally` on every path (success, error, timeout,
   cancellation, and also when closing the private event loop raises), so the thread always quits;
   cancellation emits no `error` and no `finished`.
6. **Logging.** The touched lifecycle messages moved from `print()` to `logging` (BAR-17); provider
   names use `_short_repr` (no raw CR/LF into logs), cancellation is DEBUG, a worker that misses the
   budget is WARNING.

### Tests

- `tests/unit/test_list_model_worker.py` — worker contract: success → one `finished` + one
  `stopped`, no `error`; client exception → one `error` + `stopped`, no `finished`; hanging request
  → one error mentioning the timeout and its value within the budget; mid-flight cancel through a
  real `QThread` → thread ends < 1 s, zero `finished`/`error`, one `stopped`, cancellation reached
  the client; cancel before `run()` skips the fetch entirely; repeated cancel after completion is a
  no-op; `stopped()` is emitted even when closing the private event loop raises.
- `tests/components/test_model_manager_fetch_lifecycle.py` — `stop_fetching_models` calls
  `cancel()` and `wait(ms)` with `0 < ms <= STOP_WAIT_MS`, never `terminate()`; returns within the
  budget and logs a WARNING when the thread ignores cancellation (`FakeThread.wait() == False`);
  `shutdown()` is bounded, idempotent and cleans all workers; `remove()`/reload with an active
  fetch return within the budget and leave consistent state; a result **and an error** queued by a
  stopped fetch are never applied, while an error of the current fetch is still delivered; an
  unresponsive thread stays referenced (weakref alive after `gc.collect()`); a batch stop of three
  workers is bounded by one shared deadline, not three budgets.
- `tests/system/test_model_fetch_lifecycle.py` — real local HTTP server on 127.0.0.1 that accepts
  the request and never answers, real `any_llm` client: stopping a hung fetch takes < 2 s and the
  thread `isFinished()`; `shutdown()` of three hung providers takes < 2 s, emits no `error`, leaves
  no live workers, the Qt event loop still processes events, a repeated `shutdown()` is a fast
  no-op; a hung endpoint without a stop is bounded by the timeout and reports exactly one `error`;
  an answering endpoint still delivers models through the manager.
- Existing test doubles updated to the new worker contract (`tests/system/test_model_fetch_normalization.py`
  fake client is async; `tests/components/test_model_manager_cache.py` FakeWorker has
  `cancel()`/`stopped`).
- Full suite: `513 passed, 3 deselected` (23 of them new); `uv run ruff check src tests` clean.
- Pre-fix control (new tests run against the unmodified `main` source through a scratch
  `git archive` tree + `PYTHONPATH`, so the worktree was not disturbed): unit 8 failed,
  component 1 collection error (the old manager has no `STOP_WAIT_MS`/`SHUTDOWN_BUDGET_MS`),
  system 3 failed / 1 passed (happy path only) — 11 failed + 1 collection error / 1 passed of 23,
  with `QThread: Destroyed while thread is still running` at interpreter exit — direct evidence of
  the old terminate-based defect.

### Residual risk

- Providers whose SDK call is bridged to a thread (e.g. bedrock) are cancelled from the worker's
  point of view, but the underlying non-daemon executor thread may outlive the window close;
  Python's `ThreadPoolExecutor` atexit handler joins it, so a hung bridged call can still delay
  *process* termination (the GUI and quitting are unaffected). Not fixable at the application level;
  belongs to any_llm/provider behavior.
- No explicit client-level connect/read timeouts: only the app-level total deadline (20 s) is
  guaranteed. A huge but in-time response is still parsed/validated in the GUI thread — that is
  BAR-24, and a size limit was deliberately left out of this fix (at this layer it does not reduce
  the response already parsed by the provider SDK).
- A provider that catches `CancelledError` and keeps working (or blocks the loop synchronously)
  cannot be interrupted: the GUI returns within the budget, the thread lingers (kept referenced and
  logged) until the call returns. If such a thread is still alive when the interpreter shuts down,
  Qt aborts the process (`QThread: Destroyed while thread is still running`, exit 134); with
  cooperative cancellation this is a pathological case, and `os._exit` as a last resort is
  deliberately not used.
- The exit path is still gated by **BAR-26** (issue #12): `aboutToQuit.connect(cleanup)` is only
  installed inside `App.save_language`, so a normal quit may not call `shutdown()` at all. When it
  is called, it is now bounded; BAR-26 itself is out of scope for this issue.
