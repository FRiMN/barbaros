"""Atomic, fail-safe file primitives for small per-user application data.

Mechanism only: no JSON, no cache/provider validation, no config paths.  The
two public helpers own the file-safety rules the application relies on for
regenerable data:

* reads never follow symlinks, accept only regular files and read at most the
  caller's byte limit, so a swapped or hostile file cannot block or exhaust
  the process;
* writes are atomic and durable: a same-directory temporary file with mode
  ``0600``, ``fsync``, ``os.replace`` and a best-effort directory ``fsync``; on
  any error the old file stays intact and the temporary file is removed;
* both helpers never raise: failures are logged through the *caller's* logger
  (with the caller's ``label``) so records stay attributed to the subsystem
  (e.g. ``barbaros.model_cache``) instead of a generic one.

Content validation and the write-side size policy belong to the caller: this
module only guarantees safe file mechanics.  It is not thread-safe for
concurrent writes to the same path — callers serialize writers (for example
``ModelCacheStore`` uses its own lock).

The module deliberately imports nothing from Qt, keyring or any LLM SDK.
"""

from __future__ import annotations

import contextlib
import logging
import os
import stat
import tempfile
from pathlib import Path

_READ_CHUNK_BYTES = 64 * 1024

# O_NOFOLLOW/O_NONBLOCK/O_CLOEXEC are POSIX-only; getattr keeps the module
# importable elsewhere, the same way O_BINARY is Windows-only.
_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_BINARY", 0)
)


def read_regular_file_limited(
    path: Path,
    limit: int,
    *,
    logger: logging.Logger,
    label: str = "File",
) -> bytes | None:
    """Read a regular file without following links, capped at ``limit`` bytes.

    Never raises.  Returns ``None`` (after logging) when the file is missing,
    cannot be opened or read, is not a regular file (symlink/FIFO/device/
    directory), or is larger than ``limit``.  ``limit`` is a byte count, not a
    policy: the caller decides which limit is acceptable.
    """
    fd = _open_for_read(path, logger=logger, label=label)
    if fd is None:
        return None
    return _read_capped(fd, limit, path=path, logger=logger, label=label)


def _open_for_read(path: Path, *, logger: logging.Logger, label: str) -> int | None:
    """Open ``path`` for a capped, no-follow read, without ever raising.

    Returns the raw file descriptor, or ``None`` after logging: a missing file
    is a normal state (DEBUG), any other open failure is a WARNING.  The
    caller owns the descriptor and must close it.
    """
    try:
        return os.open(path, _READ_FLAGS)
    except FileNotFoundError:
        # Normal state on first run or after the file was pruned: not a fault.
        logger.debug("%s: no file at %r", label, path)
    except Exception as exc:  # Fail-safe boundary: never propagate.
        logger.warning("%s: cannot open %r (%s)", label, path, exc.__class__.__name__)
    return None


def _read_capped(
    fd: int,
    limit: int,
    *,
    path: Path,
    logger: logging.Logger,
    label: str,
) -> bytes | None:
    """Read at most ``limit`` bytes from an already open descriptor.

    Enforces the source rules (regular file, fits into ``limit``) and always
    closes ``fd``, including on early returns.  Never raises: a rule violation
    or an I/O error is logged and reported as ``None``.
    """
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            logger.warning("%s: not a regular file, ignored: %r", label, path)
            return None

        if info.st_size > limit:
            _log_too_large(path, info.st_size, limit, logger=logger, label=label)
            return None

        data = _read_until_eof_or_limit(fd, limit)
    except Exception as exc:  # Fail-safe boundary: never propagate.
        logger.warning("%s: read failed for %r (%s)", label, path, exc.__class__.__name__)
        return None
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)

    if len(data) > limit:
        # The file grew between fstat() and read(); drop it instead of parsing.
        _log_too_large(path, len(data), limit, logger=logger, label=label)
        return None

    return data


def _read_until_eof_or_limit(fd: int, limit: int) -> bytes:
    """Read an open descriptor up to EOF or ``limit + 1`` bytes.

    The extra byte lets the caller detect a file that grew after it was
    stat'ed.  May raise ``OSError``; callers are expected to be fail-safe.
    """
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining > 0:
        chunk = os.read(fd, min(remaining, _READ_CHUNK_BYTES))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _log_too_large(
    path: Path,
    size: int,
    limit: int,
    *,
    logger: logging.Logger,
    label: str,
) -> None:
    """Log the shared ``file too large, ignored`` warning (single wording)."""
    logger.warning(
        "%s: file too large (%d > %d bytes), ignored: %r",
        label,
        size,
        limit,
        path,
    )


def write_bytes_atomic(
    path: Path,
    payload: bytes,
    *,
    logger: logging.Logger,
    label: str = "File",
) -> bool:
    """Atomically and durably replace ``path`` with ``payload``.

    Never raises.  Returns ``False`` (after logging) on any failure; the
    previous file content is left intact and the temporary file is removed.
    """
    try:
        _atomic_write(path, payload, logger=logger, label=label)
    except Exception as exc:  # Fail-safe boundary: never propagate.
        logger.warning("%s: save failed for %r (%s)", label, path, exc.__class__.__name__)
        return False
    return True


def _write_all(fd: int, payload: bytes) -> None:
    """Write all of ``payload`` to ``fd``; raise ``OSError`` on a short write."""
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write to temporary file")
        view = view[written:]


def _chmod_temp_file(fd: int, *, logger: logging.Logger, label: str) -> None:
    """Try to set mode ``0600`` on the temporary file (best effort)."""
    fchmod = getattr(os, "fchmod", None)
    if fchmod is None:  # Windows: mkstemp already creates a private file.
        return
    try:
        fchmod(fd, 0o600)
    except OSError as exc:
        logger.debug("%s: could not set temp file mode (%s)", label, exc.__class__.__name__)


def _tighten_directory(directory: Path, *, logger: logging.Logger, label: str) -> None:
    """Try to restrict the target directory to ``0700`` (best effort)."""
    try:
        os.chmod(directory, 0o700)
    except OSError as exc:
        # Best effort: saving must not fail because of permissions that are
        # already narrower (or because another user owns the directory).
        logger.debug(
            "%s: could not set directory mode on %r (%s)",
            label,
            directory,
            exc.__class__.__name__,
        )


def _fsync_directory(directory: Path, *, logger: logging.Logger, label: str) -> None:
    """Try to fsync the directory so the rename survives a power loss."""
    try:
        dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError as exc:
        logger.debug(
            "%s: could not open directory for fsync (%s)",
            label,
            exc.__class__.__name__,
        )
        return

    try:
        os.fsync(dir_fd)
    except OSError as exc:
        logger.debug("%s: directory fsync failed (%s)", label, exc.__class__.__name__)
    finally:
        with contextlib.suppress(OSError):
            os.close(dir_fd)


def _atomic_write(
    path: Path,
    payload: bytes,
    *,
    logger: logging.Logger,
    label: str,
) -> None:
    """Write ``payload`` to ``path`` atomically, keeping the old file on error."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _tighten_directory(parent, logger=logger, label=label)

    fd, temp_name = tempfile.mkstemp(prefix=".barbaros-", suffix=".tmp", dir=parent)
    temp_path = Path(temp_name)
    try:
        _chmod_temp_file(fd, logger=logger, label=label)
        try:
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp_path)
        raise

    _fsync_directory(parent, logger=logger, label=label)
