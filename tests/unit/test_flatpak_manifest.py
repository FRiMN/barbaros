"""Static checks for the BAR-28 Flatpak protection (issue #15).

The release artifact is built from ``flatpak/barbaros.yaml`` on
``io.qt.PySide.BaseApp`` 6.11, which ships PySide6 6.11.3 that still unpickles
``QSettings`` values.  The manifest must therefore override PySide6 from PyPI
with a pin >= 6.12 and run the build-time guard.  Those are release-policy
invariants: a manifest edit that drops them must fail here, not in a release.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6 import __version__ as pyside_version

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "flatpak" / "barbaros.yaml"
GUARD = REPO_ROOT / "flatpak" / "bar28_guard.py"

MIN_SAFE = (6, 12)
PIN_PATTERN = re.compile(
    r'"(pyside6-essentials|shiboken6)==(\d+)\.(\d+)\.(\d+)"'
)


def pyside_major_minor() -> tuple[int, int]:
    parts = pyside_version.split(".")
    return int(parts[0]), int(parts[1])


def manifest_text() -> str:
    return MANIFEST.read_text(encoding="utf-8")


def test_flatpak_pins_pyside_that_rejects_pickled_values():
    pins = {
        name: (int(major), int(minor))
        for name, major, minor, _patch in PIN_PATTERN.findall(manifest_text())
    }

    assert "pyside6-essentials" in pins, manifest_text()
    assert "shiboken6" in pins, manifest_text()
    # Both halves of the override must agree, or PySide6 cannot import.
    assert pins["pyside6-essentials"] == pins["shiboken6"]
    assert pins["pyside6-essentials"] >= MIN_SAFE, pins


def test_flatpak_runs_the_build_time_guard():
    text = manifest_text()

    assert "python3 bar28_guard.py" in text
    # The guard is a source of the module; a missing source entry would fail the
    # build after the expensive dependency install.
    assert f"path: {GUARD.name}" in text


def test_guard_runs_and_accepts_this_environment():
    if pyside_major_minor() < MIN_SAFE:
        pytest.skip("the development environment has a PySide6 older than 6.12")

    completed = subprocess.run(
        [sys.executable, str(GUARD)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "meets the >= 6.12 requirement" in completed.stdout
