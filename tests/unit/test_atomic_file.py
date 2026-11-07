"""Unit tests for the atomic file primitives in ``barbaros.atomic_file``.

These tests exercise the mechanism directly (no cache schema involved): safe
regular-file reads and atomic durable writes.  The ``ModelCacheStore`` tests
cover the same guarantees through its public API.
"""

from __future__ import annotations

import ast
import logging
import os
import stat
from pathlib import Path

import pytest

from barbaros import atomic_file
from barbaros.atomic_file import read_regular_file_limited, write_bytes_atomic

POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="POSIX file semantics")

LOGGER = logging.getLogger("barbaros.atomic_file")
LABEL = "Test"


def _read(path: Path, limit: int = 1024) -> bytes | None:
    return read_regular_file_limited(path, limit, logger=LOGGER, label=LABEL)


def _write(path: Path, payload: bytes = b"payload") -> bool:
    return write_bytes_atomic(path, payload, logger=LOGGER, label=LABEL)


def _temp_files(directory: Path) -> list[Path]:
    return sorted(directory.glob(".barbaros-*.tmp"))


# --- reads -----------------------------------------------------------------


def test_missing_file_returns_none_without_creating_it(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "data.json"

    assert _read(path) is None
    assert not path.exists()
    assert not path.parent.exists()


def test_missing_file_is_logged_at_debug_with_caller_context(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger=LOGGER.name):
        assert _read(tmp_path / "missing.json") is None

    records = [record for record in caplog.records if record.name == LOGGER.name]
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG
    assert records[0].getMessage().startswith(f"{LABEL}: ")


def test_reads_regular_file_bytes(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b'{"a": 1}')

    assert _read(path) == b'{"a": 1}'


def test_read_respects_exact_limit(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b"0123456789")

    assert _read(path, limit=10) == b"0123456789"
    assert _read(path, limit=9) is None


def test_oversized_file_is_rejected_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b"x" * 100)

    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        assert _read(path, limit=99) is None

    messages = [record.getMessage() for record in caplog.records]
    assert any("too large" in message for message in messages)


def test_file_growing_between_stat_and_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b"x" * 50)

    real_fstat = os.fstat

    def fake_fstat(fd: int):
        info = real_fstat(fd)
        values = list(info)
        values[stat.ST_SIZE] = 1  # pretend the file is tiny when stat'ed
        return os.stat_result(values)

    monkeypatch.setattr(atomic_file.os, "fstat", fake_fstat)
    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        assert _read(path, limit=10) is None

    assert any("too large" in record.getMessage() for record in caplog.records)


@POSIX_ONLY
def test_symlink_is_not_followed(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(b'{"secret": true}')
    link = tmp_path / "link.json"
    link.symlink_to(target)

    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        assert _read(link) is None

    assert any("cannot open" in record.getMessage() for record in caplog.records)
    assert target.read_bytes() == b'{"secret": true}'


@POSIX_ONLY
def test_fifo_is_ignored_without_blocking(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)

    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        assert _read(fifo) is None

    assert any("not a regular file" in record.getMessage() for record in caplog.records)
    assert stat.S_ISFIFO(fifo.stat().st_mode)


def test_directory_is_not_a_regular_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        assert _read(tmp_path) is None

    assert any("not a regular file" in record.getMessage() for record in caplog.records)


def test_read_error_is_logged_and_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b"data")

    def failing_read(fd: int, size: int) -> bytes:
        raise OSError("I/O error")

    monkeypatch.setattr(atomic_file.os, "read", failing_read)
    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        assert _read(path) is None

    assert any("read failed" in record.getMessage() for record in caplog.records)


def test_fstat_error_is_fail_safe_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b"data")
    closed: list[int] = []
    real_close = os.close

    def failing_fstat(fd: int):
        raise OSError("stat failed")

    def tracking_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(atomic_file.os, "fstat", failing_fstat)
    monkeypatch.setattr(atomic_file.os, "close", tracking_close)
    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        assert _read(path) is None

    assert len(closed) == 1
    assert any("read failed" in record.getMessage() for record in caplog.records)


# --- writes ----------------------------------------------------------------


def test_write_creates_parents_and_file(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "data.json"

    assert _write(path, b"new") is True
    assert path.read_bytes() == b"new"
    assert _temp_files(path.parent) == []


def test_write_replaces_existing_content(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b"old")

    assert _write(path, b"new") is True

    assert path.read_bytes() == b"new"
    assert _temp_files(tmp_path) == []


def test_write_failure_keeps_old_file_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b"old")

    def failing_replace(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(atomic_file.os, "replace", failing_replace)
    with caplog.at_level(logging.WARNING, logger=LOGGER.name):
        assert _write(path, b"new") is False

    assert path.read_bytes() == b"old"
    assert _temp_files(tmp_path) == []
    assert any("save failed" in record.getMessage() for record in caplog.records)


def test_short_write_fails_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b"old")

    monkeypatch.setattr(atomic_file.os, "write", lambda fd, view: 0)

    assert _write(path, b"new") is False
    assert path.read_bytes() == b"old"
    assert _temp_files(tmp_path) == []


def test_fsync_failure_fails_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "data.json"
    path.write_bytes(b"old")

    def failing_fsync(fd: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(atomic_file.os, "fsync", failing_fsync)

    assert _write(path, b"new") is False
    assert path.read_bytes() == b"old"
    assert _temp_files(tmp_path) == []


def test_write_to_directory_path_fails_safely(tmp_path: Path) -> None:
    directory = tmp_path / "data.json"
    directory.mkdir()

    assert _write(directory, b"new") is False
    assert directory.is_dir()
    assert _temp_files(tmp_path) == []


def test_nul_byte_path_fails_safely(tmp_path: Path) -> None:
    path = Path(f"{tmp_path}/bad\x00name.json")

    assert _read(path) is None
    assert _write(path, b"new") is False


@POSIX_ONLY
def test_fchmod_failure_is_best_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "data.json"

    def failing_fchmod(fd: int, mode: int) -> None:
        raise OSError("not permitted")

    monkeypatch.setattr(atomic_file.os, "fchmod", failing_fchmod)

    assert _write(path, b"new") is True
    assert path.read_bytes() == b"new"


@POSIX_ONLY
@pytest.mark.parametrize("umask", [0o022, 0o077])
def test_permissions_do_not_depend_on_umask(tmp_path: Path, umask: int) -> None:
    previous = os.umask(umask)
    try:
        path = tmp_path / "data.json"
        assert _write(path, b"new") is True
    finally:
        os.umask(previous)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@POSIX_ONLY
def test_existing_permissive_directory_is_tightened(tmp_path: Path) -> None:
    directory = tmp_path / "permissive"
    directory.mkdir(mode=0o755)
    os.chmod(directory, 0o755)
    path = directory / "data.json"

    assert _write(path, b"new") is True
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


# --- import hygiene --------------------------------------------------------


def test_module_imports_no_qt_keyring_or_llm_sdk() -> None:
    source = Path(atomic_file.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden = ("PySide6", "keyring", "any_llm", "barbaros")
    assert not [
        name for name in imported if name.startswith(forbidden)
    ], imported
