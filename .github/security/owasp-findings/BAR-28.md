# BAR-28 — Flatpak (PySide6 6.11.3) still unpickles `QSettings` values — sanitizer bypass → RCE

- **Issue:** https://github.com/FRiMN/barbaros/issues/15
- **Label:** `security/owasp-finding`
- **Created:** 2026-11-13
- **Source:** `docs/security/owasp-audit.md` §3 BAR-01, §4 BAR-28
- **Follow-up to:** #7 (BAR-01, closed as fixed for native/PySide6 >= 6.12 installs)

## Issue body

## Summary

BAR-01 (pickle deserialization of `QSettings` values) is fixed for the native/pip install path:
PySide6 6.12 refuses to deserialize `PySide::PyObjectWrapper`, legacy values are stripped from the
raw INI before `QSettings` is created, and the model selection is stored as JSON (commit `3e30fa3`).

The Flatpak build is **not** covered. `flatpak/barbaros.yaml` builds against
`io.qt.PySide.BaseApp` 6.11, i.e. **PySide6 6.11.3**, which still eagerly unpickles
`QSettings` values; `pyside6-essentials~=6.12.0` from `pyproject.toml` does not apply because the
manifest explicitly installs without PySide6 ("it is provided by BaseApp"). On that runtime the
settings sanitizer is the only protection, and it is bypassed by a config file larger than
`MAX_SETTINGS_BYTES` (1 MiB), by a symlinked config, or by a read-only config directory/file. In
those cases the sanitizer returns `None`/leaves the file untouched, and `QSettings.value()`
executes the pickle payload. `read_setting()` does not help: under 6.11.x the value is unpickled
before any exception can be raised.

Source: `docs/security/owasp-audit.md` §4, finding **BAR-28** (follow-up to #7 / BAR-01).

## OWASP classification

- Cheat Sheets: `Deserialization_Cheat_Sheet.md` → "Python / Clear-box Review";
  `Software_Supply_Chain_Security_Cheat_Sheet.md` → "Monitor Deployed Software for
  Vulnerabilities", "Lockfile/Version Pinning"; `Vulnerable_Dependency_Management_Cheat_Sheet.md`.
- Top-10: **A08** Software and Data Integrity Failures (2021/2025), **A06** Vulnerable and Outdated
  Components (2021), **A03** Software Supply Chain Failures (2025).
- CWE-502 (Deserialization of Untrusted Data).

## Severity

**High** for the Flatpak release artifact: a config-file write leads to code execution. Native/pip
installs with PySide6 >= 6.12 are not affected.

## Affected

- `flatpak/barbaros.yaml:3` (`runtime-version: "6.11"`), `:6` (`base-version: 6.11`), `:57-60`
  (PySide6 is not installed from pip — provided by BaseApp).
- `pyproject.toml` (`pyside6-essentials~=6.12.0` on CPython >= 3.12, `~=6.11.0` below that per BAR-29) does not affect the Flatpak build.
- `settings_sanitize.py:48` (`MAX_SETTINGS_BYTES = 1024 * 1024`), `:82-137` (fail-open sanitizer).
- `main.py:33-46` (sanitize before `QSettings`; failures only warn and continue).

## Evidence (experiments on the installed runtime)

- `io.qt.PySide.BaseApp` 6.11.3 ships `pyside6-6.11.3.dist-info` and
  `PySide6.__version__ == "6.11.3"` (Python 3.13). PySide6 6.12.0 in `.venv` refuses pickle.
- Two-process test under BaseApp 6.11.3: a writer stores `Evil.__reduce__` via
  `QSettings.setValue`; a reader in a fresh process calls `QSettings.value("main_window/model")`
  → the payload executes (marker file created). The same config under PySide6 6.12.0 raises
  `RuntimeError: Failed to deserialize Python object from QDataStream…` and the payload does not
  run.
- Sanitizer bypass: with the config padded to **1 048 817 bytes** (pickle value intact),
  `sanitize_pickled_settings()` returns `None` with WARNING "file too large" (1 MiB limit) and
  leaves the file untouched; reading it under BaseApp 6.11.3 executes the payload. A symlinked
  config (`O_NOFOLLOW` refuses the read) and a read-only config directory (backup/atomic write
  fail) likewise make the sanitizer return `None`; under 6.11.3 that still means unpickle.
- With a config <= 1 MiB, no symlink and a writable config directory, the sanitizer removes the
  pickled lines and the Flatpak path is protected — the vulnerable case is specifically the bypass.

## Scenario

An attacker with write access to `$HOME` (dotfiles sync, backup/restore, a compromised same-uid
application — all in the threat model) puts a pickle payload into
`~/.var/app/io.github.frimn.barbaros/config/io.github.frimn/barbaros.conf` and pads the file above
1 MiB (or replaces it with a symlink). On the next launch of the Flatpak build, arbitrary code runs
with the user's privileges. The payload is persistent.

## Impact

RCE in the release artifact. This bypasses exactly the fix that closed BAR-01 for the native
build; the same class/CWE but a separate exploitation path, hence a separate finding.

## Recommendation (P0)

1. Move the Flatpak build to PySide6 >= 6.12 (BaseApp 6.12 when available, or install
   `pyside6-essentials` from pip with a pin inside the Flatpak module); verify
   `PySide6.__version__` inside the built bundle.
2. Make the sanitizer **fail-closed** when PySide6 < 6.12: if the file cannot be cleaned (size,
   symlink, permissions, write error), do not let `QSettings` read it — move/rename it and start
   with clean settings (losing preferences is better than RCE), or replace `QSettings` with a JSON
   store entirely.
3. Remove the size-based bypass: stream-scan the INI instead of reading the whole file, or refuse
   to start when the limit is exceeded instead of leaving the file as is; sanitize the resolved
   target of a symlink.
4. Add a regression test on the **real Flatpak runtime**: oversize/symlinked config with a pickle
   → payload must not execute.

## Test

- BaseApp 6.11 + oversize config with pickle → sanitizer fail-closed, `QSettings` does not read
  the file, no marker.
- Built Flatpak bundle reports PySide6 >= 6.12 (`PySide6.__version__`).

## References

- `docs/security/owasp-audit.md` §3 BAR-01 and §4 BAR-28.
- `docs/settings-migration.md` §6 (Flatpak residual).
- Commit `4c9eac3` (report update), commit `3e30fa3` (BAR-01 fix).

---

## Resolution (2026-11-13)

Status: **fixed**. Fix branch `fix/bar-28-flatpak-pyside-pickle`.

1. **Flatpak runs PySide6 >= 6.12.** `io.qt.PySide.BaseApp` has no 6.12 branch on Flathub
   (latest is `branch/6.11`), so the manifest keeps BaseApp 6.11 and installs
   `pyside6-essentials==6.12.0` + `shiboken6==6.12.0` from PyPI into the bundle, overriding the
   base app's 6.11.3. `flatpak/bar28_guard.py` is a build-time guard: the build fails if the
   importable PySide6 is < 6.12 or if `QSettings` does not refuse+block a pickle payload.
2. **On PySide6 < 6.12 the settings file is not read at all.**
   `settings_sanitize.prepare_settings_file()` is called from `App.__init__` before `QSettings` is
   created. On a runtime that still unpickles it does not trust the raw-byte scan: an existing
   settings file is quarantined as `*.unsafe-<UTC>-<random>` (0600; for a symlink the link itself
   is renamed, the target is untouched) and the application uses `MemoryBackedSettings` - the
   session's settings live in memory and nothing is read from or written to disk. A throwaway
   *file* was deliberately not used: a same-uid process can replace any file the application can
   read, so only the absence of a file removes the race. On PySide6 >= 6.12 nothing is moved
   (the value is rejected by Qt and `read_setting()` degrades to defaults); the scan there is
   only legacy-data migration.
3. **Size/symlink bypass removed** for the RCE path: neither an oversized file nor a symlinked
   config is ever handed to `QSettings` on an unsafe runtime.
4. **Scan-based protection was not sufficient - the boundary is "do not read the file".** Two
   real forms evade a raw-byte scan: QSettings quotes a value when the escaped payload contains
   a comma (`0x2c` is an ordinary pickle byte, `model="@Variant(...`), and Qt unescapes
   `\xHH`/quotes **before** it decides that the value is an `@Variant` (`\x40Variant(...`,
   `PySide::PyObject\x57rapper`). Both were reproduced on the real BaseApp 6.11.3 with the old
   design (payload executed). `_is_pickled_variant()` now skips an optional leading quote for
   the >= 6.12 migration, but the security decision on < 6.12 no longer depends on the scan.

Evidence:
- `tests/system/test_flatpak_pyside.py` (opt-in, `-m slow`) on the real installed BaseApp 6.11.3
  (PySide6 6.11.3, Python 3.13): two negative controls (a plain and an escaped config read
  directly with `QSettings.value()`) execute the payload, while `prepare_settings_file()` returns
  `memory_backed=True`, quarantines any existing config and never reads it - the payload does not
  execute for plain, oversized, escaped or symlinked configs.
- Built Flatpak bundle imports PySide6 6.12.0 (verified inside the bundle); `QSettings` raises
  `RuntimeError: Failed to deserialize Python object from QDataStream...` instead of executing.
- Unit/system regression tests: `tests/unit/test_settings_sanitize.py`,
  `tests/system/test_legacy_settings.py` (the real `App` in a subprocess with the version gate
  patched to the 6.11 behaviour).

Evidence of the escaped-form bypass on the real runtime is in the final test suite:
`tests/system/test_flatpak_pyside.py` has two negative controls (plain and escaped config both
execute when read directly) and asserts that after `prepare_settings_file()` none of the
small/oversized/escaped configs is read or executed.

Residual risk: on PySide6 < 6.12 the on-disk settings are not used (preferences reset for that
session), which is the accepted fail-closed cost; no attacker-controlled path is opened by
`QSettings`. Fully closing the class is the JSON-store alternative from the recommendation; it is
tracked as separate work in `docs/settings-migration.md` Sec. 6.
