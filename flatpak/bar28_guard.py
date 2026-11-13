"""Build-time guard for BAR-28: the Flatpak module must bundle PySide6 >= 6.12.

``io.qt.PySide.BaseApp`` has no 6.12 branch on Flathub, so the manifest keeps
BaseApp 6.11 (PySide6 6.11.3, which still unpickles ``QSettings`` values) and
installs a pinned ``pyside6-essentials==6.12.0`` from PyPI on top of it. This
script makes the build fail if that override did not take effect:

* the importable ``PySide6`` must be >= 6.12 and load Qt of the same minor
  version (mixing 6.12 bindings with the base app's Qt 6.11 libraries would
  crash later);
* a pickled ``QSettings`` value must be refused in a *fresh* process and its
  payload must not run. The fresh process is required: Qt caches
  ``QSettings`` objects per file, so an in-process read can return the
  in-memory object PySide just wrote instead of deserializing the pickle.

Run by the manifest with the build sandbox's ``python3``; no QApplication and
no display are needed. This is the BAR-28 recommendation 1 check (issue #15):
"verify PySide6.__version__ inside the built bundle".
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import PySide6
import shiboken6
from PySide6.QtCore import QSettings, qVersion

MIN_PYSIDE = (6, 12)
READ_REFUSED_MARKER = "QSETTINGS_PICKLE_REFUSED"


def _minor(version: str) -> tuple[int, int]:
    try:
        return tuple(int(part) for part in version.split(".")[:2])
    except ValueError:
        return ()


def _fail(message: str) -> int:
    print(f"BAR-28 guard FAILED: {message}", file=sys.stderr)
    return 1


def _write_pickled_value(ini_path: str, marker_path: str) -> None:
    class Evil:
        def __reduce__(self):
            return (open, (marker_path, "w"))

    writer = QSettings(ini_path, QSettings.IniFormat)
    writer.beginGroup("main_window")
    writer.setValue("model", Evil())
    writer.endGroup()
    writer.sync()
    if writer.status() != QSettings.Status.NoError:
        raise RuntimeError(f"QSettings write failed: {writer.status()}")


def _reader_mode(ini_path: str) -> int:
    """Fresh process: read the value; a refusal must be raised."""
    try:
        reader = QSettings(ini_path, QSettings.IniFormat)
        reader.beginGroup("main_window")
        reader.value("model")
        reader.endGroup()
    except RuntimeError as exc:
        print(f"{READ_REFUSED_MARKER} {exc}")
        return 0
    print("QSETTINGS_PICKLE_EXECUTED", file=sys.stderr)
    return 1


def main() -> int:
    version = PySide6.__version__
    pyside_minor = _minor(version)
    qt_minor = _minor(qVersion())

    if pyside_minor < MIN_PYSIDE:
        return _fail(
            f"importable PySide6 is {version} ({PySide6.__file__}), need >= 6.12"
        )
    if shiboken6.__version__ != version:
        return _fail(
            f"PySide6 {version} is paired with shiboken6 {shiboken6.__version__}; "
            "the two must come from the same release"
        )
    if qt_minor != pyside_minor:
        return _fail(
            f"PySide6 {version} is bound to Qt {qVersion()}; the module mixes "
            f"PySide6 {pyside_minor} with older Qt libraries from the base app"
        )

    print(
        f"BAR-28 guard: PySide6 {version} / shiboken6 {shiboken6.__version__} "
        f"/ Qt {qVersion()} from {PySide6.__file__}"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        ini_path = os.path.join(tmpdir, "guard.conf")
        marker_path = os.path.join(tmpdir, "marker")
        _write_pickled_value(ini_path, marker_path)

        completed = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--reader", ini_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0 or READ_REFUSED_MARKER not in completed.stdout:
            return _fail(
                "PySide6 did not refuse a pickled QSettings value in a fresh "
                f"process (exit={completed.returncode}, "
                f"stdout={completed.stdout.strip()!r}, "
                f"stderr={completed.stderr.strip()!r})"
            )

        if os.path.exists(marker_path):
            return _fail("the pickle payload executed during the guard read")

    print(f"BAR-28 guard: PySide6 {version} meets the >= 6.12 requirement")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--reader":
        sys.exit(_reader_mode(sys.argv[2]))
    sys.exit(main())
