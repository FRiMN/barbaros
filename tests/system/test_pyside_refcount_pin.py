"""Regression tests for the PySide6 6.12.0 singleton refcount leak (BAR-29, #20).

PySide6 6.12.0 wheels drop one reference to the ``None`` singleton on every
ordinary void Qt call and one reference to ``True`` on every ``Signal.emit()``.
On CPython < 3.12 those singletons are not immortal, so the count eventually
reaches zero and the interpreter aborts with ``Fatal Python error:
none_dealloc`` / ``bool_dealloc``.  The upstream fix (PYSIDE-3474) is build-only
and lands in 6.12.1, so until it is released ``pyproject.toml`` pins PySide6 to
the 6.11 line on CPython < 3.12.

Three independent layers are covered:

* an in-process canary over representative void calls (fast and precise - it
  fails by a refcount delta long before the process aborts);
* the real ``GradientRainbowLabel`` animation in a subprocess - the reported
  user-visible crash path, because every paint event issues several void Qt
  calls per frame.  A fixed wheel may add (cache) a few singleton references
  while running, so the child must never *lose* references, not stay exactly
  flat: a negative delta is the 6.12.0 leak showing up before the abort;
* the environment contract: the PySide6 distribution installed in the running
  interpreter must satisfy the requirement branch that ``pyproject.toml``
  selects for that interpreter.  This is what makes the marker pin itself
  testable instead of an unverified comment.
"""

from __future__ import annotations

import gc
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import textwrap
import tomllib
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import NamedTuple

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"

# 100 calls is enough to see the leak on a broken build (one reference lost per
# call) while staying instant and unlikely to trip any external cache.
REFCOUNT_CALLS = 100

# The reported crash shows up within a moment of the first animated paint
# events; two seconds of animation is a comfortable margin over that.
ANIMATION_SECONDS = 2.0
ANIMATION_MS = int(ANIMATION_SECONDS * 1000)
ANIMATION_TIMEOUT_SECONDS = 60

RESULT_PREFIX = "REFCOUNT_RESULT "


# --- in-process canary -------------------------------------------------------

class RefCountEmitter(QObject):
    """Minimal signal source for the ``Signal.emit`` canary."""

    emitted = Signal()


class SingletonRefCounts(NamedTuple):
    none_refs: int
    true_refs: int


def measure_singleton_refcounts(
    operation: Callable[[], object], *, calls: int = REFCOUNT_CALLS
) -> tuple[SingletonRefCounts, SingletonRefCounts]:
    """Return ``None``/``True`` refcounts before and after ``calls`` calls.

    A warm-up call runs first: the first call may populate caches, and the
    baseline must be taken afterwards so only the repeated calls are measured.
    The cyclic GC is paused for the measurement window so that collecting
    unrelated cycles cannot move the counts and produce a false positive.
    """
    gc_enabled = gc.isenabled()
    gc.disable()
    try:
        operation()  # warm-up
        gc.collect()
        before = SingletonRefCounts(sys.getrefcount(None), sys.getrefcount(True))
        for _ in range(calls):
            operation()
        after = SingletonRefCounts(sys.getrefcount(None), sys.getrefcount(True))
    finally:
        if gc_enabled:
            gc.enable()

    return before, after


def test_singleton_refcounts_do_not_drop_on_qt_calls():
    if platform.python_implementation() != "CPython":
        pytest.skip("sys.getrefcount() is only meaningful on CPython")

    label = QLabel("refcount canary")
    color = QColor(10, 20, 30)
    # The emitter must stay alive: a signal on an object collected right away
    # has nothing to emit from and would make the canary vacuous.
    emitter = RefCountEmitter()

    operations = [
        ("QLabel.setText", partial(label.setText, "refcount canary")),
        ("QColor.setAlpha", partial(color.setAlpha, color.alpha())),
        ("QWidget.resize", partial(label.resize, label.width(), label.height())),
        ("Signal.emit", emitter.emitted.emit),
    ]
    measured = [
        (name, *measure_singleton_refcounts(operation))
        for name, operation in operations
    ]

    environment = f"CPython {platform.python_version()}, PySide6 {pyside_version}"
    problems = [
        f"{name}: None {before.none_refs} -> {after.none_refs} "
        f"(delta {after.none_refs - before.none_refs}); "
        f"True {before.true_refs} -> {after.true_refs} "
        f"(delta {after.true_refs - before.true_refs})"
        for name, before, after in measured
        if before != after
    ]

    assert not problems, (
        "Ordinary Qt calls must not change the refcount of the None/True "
        f"singletons (PYSIDE-3474, BAR-29); environment: {environment}\n"
        + "\n".join(problems)
    )


# --- the reported crash path: an animated label -----------------------------

ANIMATION_SCRIPT = textwrap.dedent(
    '''
    """Show the real gradient animation offscreen and report refcount deltas."""

    import json
    import os
    import platform
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from barbaros.widgets.progress_label import GradientRainbowLabel

    app = QApplication([])
    none_before = sys.getrefcount(None)
    true_before = sys.getrefcount(True)

    label = GradientRainbowLabel("Translating...")
    label.resize(400, 60)
    label.show()
    label.start_animation()
    QTimer.singleShot(%ANIMATION_MS%, app.quit)
    quit_code = app.exec()

    none_after = sys.getrefcount(None)
    true_after = sys.getrefcount(True)
    print(
        "%RESULT_PREFIX%"
        + json.dumps(
            {
                "implementation": platform.python_implementation(),
                "python": platform.python_version(),
                "pyside6": pyside_version,
                "none_before": none_before,
                "none_after": none_after,
                "none_delta": none_after - none_before,
                "true_before": true_before,
                "true_after": true_after,
                "true_delta": true_after - true_before,
                "quit_code": quit_code,
            }
        )
    )
    '''
).replace("%ANIMATION_MS%", str(ANIMATION_MS)).replace(
    "%RESULT_PREFIX%", RESULT_PREFIX
)


def run_animation_subprocess(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run ``ANIMATION_SCRIPT`` on the current interpreter and capture output."""
    script = tmp_path / "gradient_animation_refcounts.py"
    script.write_text(ANIMATION_SCRIPT, encoding="utf-8")

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    # The child must import the checked-out sources, not an unrelated install.
    env["PYTHONPATH"] = str(REPO_ROOT / "src")

    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=ANIMATION_TIMEOUT_SECONDS,
        check=False,
        env=env,
    )


def describe_child_crash(completed: subprocess.CompletedProcess[str]) -> str:
    """Build an actionable failure message for a crashed child."""
    if completed.returncode < 0:
        outcome = f"the child was killed by signal {-completed.returncode}"
    else:
        outcome = f"the child exited with status {completed.returncode}"

    lines = [
        "The offscreen GradientRainbowLabel animation did not exit cleanly: "
        f"{outcome}.",
        "On CPython < 3.12 a crash here is the BAR-29 symptom: PySide6 6.12.0 "
        "leaks None/True references, and the interpreter aborts with "
        "'Fatal Python error: none_dealloc' or 'bool_dealloc'.",
    ]
    if "Fatal Python error" in completed.stderr:
        lines.append(
            "The child stderr contains a fatal Python error "
            "(singleton refcount corruption)."
        )
    lines += [
        "--- child stdout ---",
        completed.stdout or "<empty>",
        "--- child stderr ---",
        completed.stderr or "<empty>",
    ]
    return "\n".join(lines)


def test_gradient_rainbow_label_animation_exits_cleanly(tmp_path):
    completed = run_animation_subprocess(tmp_path)

    assert completed.returncode == 0, describe_child_crash(completed)

    markers = [
        line[len(RESULT_PREFIX) :]
        for line in completed.stdout.splitlines()
        if line.startswith(RESULT_PREFIX)
    ]
    assert len(markers) == 1, (
        f"expected exactly one {RESULT_PREFIX.strip()} marker in child stdout, "
        f"got {len(markers)}\n--- child stdout ---\n{completed.stdout}"
    )
    result = json.loads(markers[0])

    environment = (
        f"{result['implementation']} {result['python']}, "
        f"PySide6 {result['pyside6']}"
    )
    deltas = [
        f"None: {result['none_before']} -> {result['none_after']} "
        f"(delta {result['none_delta']})",
        f"True: {result['true_before']} -> {result['true_after']} "
        f"(delta {result['true_delta']})",
    ]
    # The leak is a *lost* reference per call.  A fixed wheel can cache a few
    # singleton references while the animation runs (older PySide keeps extra
    # references on void returns), so only a negative delta is a failure here;
    # the exact "delta 0" contract for ordinary calls is the in-process canary.
    assert result["none_delta"] >= 0 and result["true_delta"] >= 0, (
        "the animated label lost references to the None/True singletons "
        "(PYSIDE-3474, BAR-29), which precedes the interpreter abort; "
        f"environment: {environment}\n" + "\n".join(deltas)
    )


# --- environment contract: pyproject markers vs installed PySide6 ------------

def load_pyproject() -> dict:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def active_requirement(
    entries: list[str], package_name: str, source: str
) -> Requirement:
    """Return the ``package_name`` requirement that applies to this interpreter."""
    declared = [Requirement(entry) for entry in entries]
    matching = [
        requirement
        for requirement in declared
        if canonicalize_name(requirement.name) == canonicalize_name(package_name)
    ]
    active = [
        requirement
        for requirement in matching
        if requirement.marker is None or requirement.marker.evaluate()
    ]
    assert len(active) == 1, (
        f"{source} must declare exactly one {package_name} requirement for "
        f"CPython {platform.python_version()}; declared: "
        f"{[str(requirement) for requirement in matching]}"
    )
    return active[0]


def check_installed_version(
    entries: list[str], package_name: str, source: str
) -> None:
    """Assert the installed distribution satisfies the selected requirement."""
    requirement = active_requirement(entries, package_name, source)
    try:
        installed = importlib.metadata.version(requirement.name)
    except importlib.metadata.PackageNotFoundError:
        pytest.fail(
            f"{source} requires {requirement}, but {requirement.name} is not "
            f"installed for this interpreter ({sys.executable}). Run `uv sync`."
        )

    assert installed in requirement.specifier, (
        f"{source} selects {requirement} on CPython "
        f"{platform.python_version()}, but {requirement.name} {installed} is "
        f"installed ({sys.executable}). Expected {requirement.specifier}; "
        "run `uv sync` so the environment follows the pyproject.toml marker "
        "branch. BAR-29: the CPython < 3.12 branch exists because PySide6 6.12 "
        "aborts on leaked None/True references."
    )


def test_installed_pyside_matches_pyproject_policy():
    pyproject = load_pyproject()

    check_installed_version(
        pyproject["project"]["dependencies"],
        "pyside6-essentials",
        "[project].dependencies",
    )
    check_installed_version(
        pyproject["dependency-groups"]["dev"],
        "pyside6",
        "[dependency-groups].dev",
    )
