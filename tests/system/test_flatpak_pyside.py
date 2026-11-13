"""Opt-in regression test for BAR-28 on the real old Flatpak runtime.

The Flatpak release shipped PySide6 6.11.3 from ``io.qt.PySide.BaseApp`` 6.11,
which eagerly unpickles ``QSettings`` values.  The unit/system tests simulate
that runtime by patching the version gate; this test runs the actual code under
the installed BaseApp 6.11 and checks both halves of the fix:

* negative control - reading a hostile config directly with ``QSettings``
  executes the payload on that runtime (so the test is not vacuous);
* the application path - ``prepare_settings_file`` quarantines the existing
  config, the session is memory-backed and nothing is ever read from disk.

It requires ``flatpak``, the ``io.qt.PySide.BaseApp//6.11`` runtime and network
is not used.  It is marked ``slow`` (excluded by the default ``addopts``) and
skips itself when the runtime is missing, so ordinary runs are unaffected:

    uv run pytest -m slow tests/system/test_flatpak_pyside.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

import barbaros
from barbaros.settings_sanitize import MAX_SETTINGS_BYTES, PICKLE_MARKER

BASE_APP = "io.qt.PySide.BaseApp//6.11"
BASE_APP_TIMEOUT_SECONDS = 60
REPO_ROOT = Path(barbaros.__file__).resolve().parents[2]
RESULT_PREFIX = "FLATPAK_RESULT "

# flatpak gives the sandboxed process a private /tmp, so the script, the configs
# and the marker must live on a bind-mounted path.  This directory is
# gitignored and independent from ``build/``/``repo/`` (used by flatpak-builder).
HARNESS_ROOT = REPO_ROOT / ".pytest-flatpak"


def base_app_available() -> bool:
    if shutil.which("flatpak") is None:
        return False
    try:
        completed = subprocess.run(
            ["flatpak", "info", BASE_APP],
            capture_output=True,
            text=True,
            timeout=BASE_APP_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not base_app_available(),
        reason=f"{BASE_APP} is not installed in this environment",
    ),
]


def sandbox_env(home: Path) -> dict[str, str]:
    """A private HOME/XDG set: flatpak writes its per-app dirs under HOME.

    The developer's real ``~/.var`` may be read-only or must stay untouched.
    """
    home.mkdir(parents=True, exist_ok=True)
    (home / ".local" / "share").mkdir(parents=True)
    (home / ".cache").mkdir()
    runtime_dir = home / "runtime"
    runtime_dir.mkdir(mode=0o700)
    (runtime_dir / "flatpak").mkdir()

    env = os.environ.copy()
    env.update(
        HOME=str(home),
        XDG_RUNTIME_DIR=str(runtime_dir),
        XDG_CACHE_HOME=str(home / ".cache"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_CONFIG_HOME=str(home / ".config"),
        # No session bus inside the test sandbox: flatpak skips its D-Bus proxy.
        DBUS_SESSION_BUS_ADDRESS="disabled:",
    )
    return env


def write_hostile_config(path: Path, marker: Path) -> None:
    """A QSettings value whose unpickling writes ``marker`` (the payload)."""

    class Payload:
        def __init__(self, target):
            self.target = target

        def __reduce__(self):
            return (open, (self.target, "w"))

    path.parent.mkdir(parents=True, exist_ok=True)
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    settings.setValue("main_window/model", Payload(str(marker)))
    settings.setValue("main_window/target_language", "ru")
    settings.sync()
    assert PICKLE_MARKER in path.read_bytes()


RUNTIME_SCRIPT = textwrap.dedent(
    """
    import json
    import sys
    from pathlib import Path

    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QSettings

    from barbaros.settings_sanitize import MemoryBackedSettings, prepare_settings_file

    workdir = Path(sys.argv[1])
    result = {"pyside": pyside_version}

    def read_settings(path):
        \"\"\"Read the legacy key; return the exception class name, if any.\"\"\"
        settings = QSettings(str(path), QSettings.Format.IniFormat)
        try:
            settings.value("main_window/model")
        except Exception as exc:  # noqa: BLE001 - the point is the class name
            return exc.__class__.__name__
        return None

    def record(name, prepared, original):
        # Emulate the application: memory-backed on this runtime, no file read.
        marker = workdir / "PWNED"
        result[name + "_memory_backed"] = prepared.memory_backed
        result[name + "_quarantined"] = prepared.quarantined is not None
        result[name + "_path_exists"] = original.exists()
        settings = MemoryBackedSettings()
        result[name + "_read_error"] = None
        result[name + "_read_value"] = settings.value("main_window/model")
        result[name + "_read_executed"] = marker.exists()
        if marker.exists():
            marker.unlink()

    # 1. Negative controls: this runtime really executes the pickle, both in the
    #    plain form and in the escaped form that a raw-byte scan cannot see.
    for name in ("hostile", "hostile-escaped"):
        marker = workdir / "PWNED"
        config = workdir / (name + ".conf")
        result[name + "_direct_error"] = read_settings(config)
        result[name + "_direct_executed"] = marker.exists()
        if marker.exists():
            marker.unlink()

    # 2-4. Application path: on this runtime the file must not be read at all.
    for name, config in (
        ("small", workdir / "hostile-small.conf"),
        ("big", workdir / "hostile-big.conf"),
        ("escaped", workdir / "hostile-escaped-app.conf"),
    ):
        record(name, prepare_settings_file(config), config)

    print("FLATPAK_RESULT " + json.dumps(result))
    """
)


@pytest.fixture
def harness():
    """A scratch directory under the repository (see ``HARNESS_ROOT``)."""
    HARNESS_ROOT.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=HARNESS_ROOT))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def escape_variant(config: bytes) -> bytes:
    """Hide the variant from a raw-byte scan; Qt unescapes it before parsing."""
    return config.replace(b"=@Variant(", b"=\\x40Variant(").replace(
        b"PySide::PyObjectWrapper", b"PySide::PyObject\\x57rapper"
    )


def run_sandboxed(harness: Path) -> dict:
    workdir = harness / "work"
    workdir.mkdir()
    marker = workdir / "PWNED"

    small = workdir / "hostile-small.conf"
    write_hostile_config(small, marker)
    big = workdir / "hostile-big.conf"
    big.write_bytes(small.read_bytes() + b" " * MAX_SETTINGS_BYTES)
    escaped = escape_variant(small.read_bytes())
    (workdir / "hostile-escaped-app.conf").write_bytes(escaped)
    (workdir / "hostile-escaped.conf").write_bytes(escaped)
    # Plain config: the negative control (read directly, not via the app).
    write_hostile_config(workdir / "hostile.conf", marker)

    script = workdir / "runtime_script.py"
    script.write_text(RUNTIME_SCRIPT, encoding="utf-8")

    env = sandbox_env(harness / "home")
    completed = subprocess.run(
        [
            "flatpak",
            "run",
            f"--filesystem={REPO_ROOT}:ro",
            f"--filesystem={harness}",
            f"--env=PYTHONPATH={REPO_ROOT / 'src'}",
            "--command=python3",
            BASE_APP,
            str(script),
            str(workdir),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Traceback (most recent call last)" not in completed.stderr, completed.stderr

    lines = [
        line[len(RESULT_PREFIX) :]
        for line in completed.stdout.splitlines()
        if line.startswith(RESULT_PREFIX)
    ]
    assert len(lines) == 1, completed.stdout
    return json.loads(lines[0])


def test_old_flatpak_runtime_cannot_reach_qsettings_with_a_pickle(harness):
    result = run_sandboxed(harness)

    # The test must run on the vulnerable runtime to mean anything.
    major_minor = tuple(int(part) for part in result["pyside"].split(".")[:2])
    if major_minor >= (6, 12):
        pytest.skip(f"runtime no longer unpickles (PySide6 {result['pyside']})")
    # Both negative controls: this runtime executes the pickle, in the plain
    # and in the escaped (scan-invisible) form.
    assert result["hostile_direct_executed"] is True
    assert result["hostile-escaped_direct_executed"] is True

    # Every existing config is quarantined and the session is memory-backed:
    # the on-disk bytes are never handed to QSettings, so no payload runs.
    for name in ("small", "big", "escaped"):
        assert result[name + "_memory_backed"] is True
        assert result[name + "_quarantined"] is True
        assert result[name + "_path_exists"] is False
        assert result[name + "_read_value"] is None
        assert result[name + "_read_executed"] is False
