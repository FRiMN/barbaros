# BAR-19 — `model_cache_path` is an arbitrary write sink — overwrites/destroys any user-writable file

- **Issue:** https://github.com/FRiMN/barbaros/issues/6
- **Label:** `security/owasp-finding`
- **Created:** 2026-11-09
- **Fixed:** 2026-11-13
- **Source:** `docs/security/owasp-audit.md` §2/§4 BAR-19
- **Related:** #7 (BAR-01) — same root premise (config is untrusted input), different sink

## Issue body

## Summary

`model_cache_path` from the Barbaros config is accepted as **any absolute path** and used as a
write sink without verifying that the target is "our cache file". On the first `set_models` /
`remove`, `os.replace(temp, path)` atomically overwrites **any user-writable file** — `.bashrc`,
another application's config, a FIFO — with the cache JSON. The old data is destroyed without
warning. This is a distinct destructive sink that survives fixing BAR-01 (config is trusted).

Source: `docs/security/owasp-audit.md` §4, finding **BAR-19**.

## OWASP classification

- Cheat Sheets: `Secure_Code_Review_Cheat_Sheet.md` → "Injection Vulnerabilities" (unsafe file
  path construction), "Data Flow Analysis" (sink: file write); `Input_Validation_Cheat_Sheet.md`
  → "Parse Safely, Then Validate"; `Attack_Surface_Analysis_Cheat_Sheet.md`.
- Top-10: **A04** Insecure Design, **A08** Software and Data Integrity Failures.
- CWE-73 (External Control of File Name or Path), CWE-15 (External Control of System or
  Configuration Setting).

## Severity

**Medium** — silent destructive write (integrity/availability), a separate class from RCE. There
is no direct escalation beyond BAR-01 (whoever can write the config can usually write files), but
the sink survives fixing BAR-01 and "config data travels between machines" (dotfiles / sync /
backup) makes it independently reachable.

## Location

- `main_window.py:44-52` — path from `QSettings` passed to `ModelCacheStore(path=...)`.
- `model_cache.py:51-100` (`cache_path_from_config`) — accepts any absolute path (`~` / `~user`
  are expanded; relative / non-string are rejected).
- `atomic_file.py:283-312` (`_atomic_write`) — `parent.mkdir(...)`, `mkstemp`,
  `os.replace(temp, path)` with no check that `path` is a cache file.
- `atomic_file.py:247-259` (`_tighten_directory`) — `os.chmod(directory, 0o700)` follows
  symlinks (in prod only for the default path, but `ModelCacheStore(path=..., tighten_directory=True)`
  is a public API footgun).

## Evidence (experiments)

1. **Overwrite of an existing file**: a `0o644` file containing `IMPORTANT USER DATA` became
   `0o600` with `{"version":1,"models":{…}}` after `save()`; the original data was lost.
   `cache_path_from_config('~/.bashrc')` → `~/.bashrc` (expanded to the user's home),
   `cache_path_from_config('/etc/passwd')` → `/etc/passwd`.
2. **Symlink target on write**: `os.replace` replaces the link itself, not the target (good).
   Symlink **parent** + `tighten_directory=True`: the write follows the link into a foreign
   directory and `chmod 0700` changes that directory's mode (0755 → 0700).
3. **FIFO as target**: `save() == True`, the special file is destroyed (becomes a regular JSON);
   `/dev/full` → `False`; directory target → `False`; read-only dir / ENOSPC / `os.replace`
   failure / serialization failure → `False` with the old file intact and the temp removed.
4. `cache_path_from_config` matrix: absolute / `~` / `~user` → `Path`; relative / empty /
   `file://` / non-string / unknown `~user` → `None` (fail-safe); NUL / newline paths are accepted
   at validation and safely fail later.

## Scenario

The Barbaros config arrives on a machine via dotfiles / backup / another install, or is edited by
a compromised same-uid application, with `model_cache_path=<path to someone else's file>`. On the
first `set_models` / `remove`, the app atomically replaces the named file (or FIFO) with cache
contents. The "accidental" variant: the user mistakenly points at an existing file — the README
warns, but only in the README, not in code or UI.

## Impact

Irreversible data loss in an arbitrary user-writable file, corruption of other applications'
configs, destruction of special files. No RCE or secret leakage: content is bounded by the cache
schema, the file is `0600` (not executable), keys / `api_base` are not written.

## Recommendation (KISS)

1. Before the first write: if `path` exists and (`path.is_symlink()` or not a regular file or not
   parseable by `ModelCacheDocument.from_bytes`) — refuse (`WARNING`, `return False`) without
   deleting the file. One check on top of `read_regular_file_limited`; the cache is regenerable,
   the foreign file stays intact.
2. `_tighten_directory`: do not follow symlinks (`os.chmod(..., follow_symlinks=False)` or skip
   chmod when `directory.is_symlink()`); remove `tighten_directory` from the public API — the
   store itself knows whether it resolved the default path.
3. In README / docstrings, do not promise "point at the cache file" — back it with the guard from
   item 1; state explicitly that `model_cache_path` is "a path the app will overwrite".
4. In the UI, warn on a non-standard path (or do not expose this in config at all — YAGNI).

## Test

- `test_save_refuses_to_overwrite_non_cache_file` (existing `.bashrc` / FIFO / symlink →
  `save() is False`, file byte-identical, no temp left).
- `test_tighten_directory_does_not_follow_symlink`.

## Resolution (2026-11-13)

Status: **fixed**. Fix branch `fix/bar-19-cache-write-guard`; PR closes #6.

The owner's decision (issue discussion) was deliberately **less strict than recommendation 1**:
the write guard accepts an existing file if it is a model-cache document of **any** schema
version, not only the current version. That keeps a downgrade/upgrade able to refresh the cache
(it is regenerable data) while still refusing everything that is not ours.

### Changes

1. **Write guard before `os.replace`** — `ModelCacheStore._may_replace()` (under the store's write
   lock: `os.lstat` → missing target is writable; otherwise the target must be a regular file,
   read with the existing no-follow/capped `read_regular_file_limited` and checked by the new
   `ModelCacheDocument.is_cache_document()`, which accepts the envelope `{"version": <int>,
   "models": {...}}` of any version). Symlink, FIFO, device, directory, unreadable, oversized,
   corrupt and foreign files are left byte-for-byte intact; `save()` returns `False` and logs a
   WARNING with the path (no file content). After a successful write the target's identity
   (device/inode/size/mtime_ns/ctime_ns) is memoized and an unchanged own file is not re-read on
   every save (`73 ms` per save at 3.4 MB otherwise, on top of BAR-20); repeated identical
   refusals log once (WARNING, then DEBUG). The check and `replace` are not one atomic operation;
   a same-uid process is outside the audit threat model (BAR-10), the guard targets accidental,
   synced and foreign files.
2. **No `chmod` through a symlinked path** — `_tighten_directory()` skips a directory when any
   component of its path is a symbolic link (`_has_symlink_component`), so a foreign directory's
   mode is never changed (the immediate-parent check was found insufficient by review: `chmod`
   follows intermediate components too). `write_bytes_atomic(..., tighten_directory=...)` is now
   opt-in (`False` by default); the store explicitly enables it only for the app-resolved default
   path.
3. **Public API footgun removed** — `ModelCacheStore(path, *, tighten_directory=...)` is now
   `ModelCacheStore(path)`; the store tightens the directory only for the app-resolved default
   path and never for an explicitly passed `model_cache_path`.
4. **Docs** — README and README_RU now state that the file is replaced only if it is missing or
   already a Barbaros model cache (any version), that a file not recognized as a cache is never
   touched, and that the model list is not persisted until such a file is moved aside. The
   storage design doc (§4.1, §4.6, §5.1, §7.2, §12) and `docs/security/owasp-audit.md` were
   updated; the audit records BAR-19 as fixed with evidence and residual risk.

### Tests

- `tests/unit/test_model_cache.py` — foreign-file matrix (10 shapes) → `False`, bytes/mode
  unchanged, no temp; cache versions 0/1/2/999, invalid entries and a file exactly at the 4 MiB
  limit → `save()` allowed; FIFO / directory / symlink / dangling symlink / oversized /
  unreadable targets → `False`; hardlink: the other link keeps its bytes; a repeated save of the
  store's own unchanged file does not parse it, an external change does; repeated refusal logs a
  single WARNING; refusal log contains the path but not file contents; `is_cache_document`
  envelope matrix.
- `tests/system/test_model_cache_security.py` — real `MainWindow` with `model_cache_path`
  pointing at an existing foreign file, and with a foreign file at the default path: after
  `set_models` the file is byte-identical, mode unchanged, no temp, nothing written to the other
  location.
- `tests/unit/test_atomic_file.py` — the target directory keeps its `0755` mode when reached via
  an immediate symlink parent *and* via an intermediate symlink component; the file is created
  `0600` and the link is preserved; tightening is opt-in.
- Full suite `481 passed, 3 deselected`; `uv run ruff check src tests` clean.

### Residual risk

- **Envelope heuristic**: a foreign JSON that happens to be `{"version": <int>, "models": {...}}`
  would be treated as a cache. This is the accepted trade-off of the owner's "any version"
  decision; the reverse failure (refusing a real cache of another version) would break the cache.
  "Any version" is also bounded by the store's 4 MiB read cap: a larger file cannot be verified
  and is refused.
- **TOCTOU**: a same-uid process can still swap the target between the check and `os.replace`.
  That process is outside the audit threat model (it can already write the file).
- **No self-healing for a corrupt cache**: a corrupt cache is now refused instead of being
  overwritten on the next save; the user must move/remove the file. This is the price of never
  overwriting a file the app cannot prove is its own; the log message says what to do, and the
  model list is not persisted until then.
- UI warning for a non-standard path (recommendation 4) is deliberately not part of this fix.
