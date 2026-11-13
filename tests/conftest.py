"""Shared test configuration.

Qt GUI tests must be able to create a QApplication without a display (CI,
headless runs). The offscreen platform keeps rendering tests deterministic;
an explicitly configured QT_QPA_PLATFORM still wins.

XDG directories are redirected to a throwaway directory *before* any Qt or
application import: QSettings caches its base directory on first use, so a
per-test redirect would be too late for it.  Tests that need QSettings always
use an explicit file path (see ``fake_settings``/``FakeApp``), and tests that
exercise the default model-cache location redirect ``XDG_DATA_HOME`` with the
``data_home`` fixture (QStandardPaths resolves it dynamically).
"""

import atexit
import json
import os
import shutil
import tempfile
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_XDG_ROOT = tempfile.mkdtemp(prefix="barbaros-tests-")
for _xdg_subdir in ("config", "cache", "data"):
    os.environ[f"XDG_{_xdg_subdir.upper()}_HOME"] = os.path.join(_XDG_ROOT, _xdg_subdir)

atexit.register(shutil.rmtree, _XDG_ROOT, ignore_errors=True)


# --- helpers (also exposed as fixtures, so tests do not import conftest) -----

def make_models(count: int, *, prefix: str = "model") -> list[dict]:
    """Return ``count`` cache-entry dicts in the allowlisted shape."""
    return [
        {
            "id": f"{prefix}-{index}",
            "created": 1_710_000_000 + index,
            "object": "model",
            "owned_by": "tester",
        }
        for index in range(count)
    ]


def cache_doc(models: dict[str, list[dict]], *, version: int = 1) -> dict:
    """Wrap a ``{provider: [model, ...]}`` mapping in the on-disk document."""
    return {"version": version, "models": models}


def write_cache(path, data) -> "os.PathLike":
    """Write ``data`` as the JSON cache file at ``path`` (creating parents)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def wait_until(predicate, *, timeout: float = 5.0) -> bool:
    """Spin the Qt event loop until ``predicate()`` is true or ``timeout``."""
    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return bool(predicate())


# --- Qt ---------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def qapp():
    """One QApplication for the whole session; never destroyed."""
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    application.setOrganizationDomain("io.github.frimn")
    application.setApplicationName("barbaros")
    return application


# --- keyring ----------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_keyring():
    """In-memory keyring so tests never touch the user's Secret Service."""
    import keyring
    from keyring.backend import KeyringBackend
    from keyring.errors import PasswordDeleteError

    class MemoryKeyring(KeyringBackend):
        priority = 1

        def __init__(self):
            self.passwords: dict[tuple[str, str], str] = {}

        def get_password(self, service, username):
            return self.passwords.get((service, username))

        def set_password(self, service, username, password):
            self.passwords[(service, username)] = password

        def delete_password(self, service, username):
            try:
                del self.passwords[(service, username)]
            except KeyError:
                raise PasswordDeleteError(f"no password for {username!r}") from None

    try:
        previous = keyring.get_keyring()
    except Exception:  # pragma: no cover - platform-dependent
        previous = None
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    if previous is not None:
        keyring.set_keyring(previous)


@pytest.fixture
def no_keyring(fake_keyring):
    """Switch keyring to the fail backend (no usable Secret Service)."""
    import keyring
    from keyring.backends import fail

    keyring.set_keyring(fail.Keyring())
    yield
    keyring.set_keyring(fake_keyring)


# --- QSettings / App stand-ins ---------------------------------------------

class FakeApp:
    """Minimal stand-in for ``barbaros.main.App`` used by window-level tests."""

    def __init__(self, settings):
        self.settings = settings
        self.saved_languages: list[str] = []

    def save_language(self, lang: str) -> None:
        self.saved_languages.append(lang)


@pytest.fixture
def fake_settings(tmp_path):
    """QSettings backed by an explicit temporary INI file."""
    from PySide6.QtCore import QSettings

    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def fake_app(fake_settings):
    return FakeApp(fake_settings)


# --- filesystem / helpers fixtures -----------------------------------------

@pytest.fixture
def data_home(tmp_path, monkeypatch):
    """Per-test XDG_DATA_HOME for tests of the default cache location."""
    root = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(root))
    return root


@pytest.fixture(name="make_models")
def make_models_fixture():
    return make_models


@pytest.fixture(name="cache_doc")
def cache_doc_fixture():
    return cache_doc


@pytest.fixture(name="write_cache")
def write_cache_fixture():
    return write_cache


@pytest.fixture(name="wait_until")
def wait_until_fixture():
    return wait_until


# --- legacy QSettings fixtures (BAR-01) ------------------------------------

# What PySide6 writes for ``QSettings.setValue()`` with a Python object: a
# QVariant of the ``PySide::PyObjectWrapper`` meta type holding a pickle.  The
# payload below is a benign pickle of ``ModelSelection`` (older Barbaros
# versions wrote exactly this shape); no test executes it.
LEGACY_PICKLE_LINE = (
    rb"model=@Variant(\0\0\0\x7f\0\0\0\x18PySide::PyObjectWrapper\0\0\0\0}"
    rb"\x80\x4\x95r\0\0\0\0\0\0\0\x8c$barbaros.widgets.filterable_combobox"
    rb"\x94\x8c\xeModelSelection\x94\x93\x94)\x81\x94}\x94(\x8c\bprovider"
    rb"\x94\x8c\bdeepseek\x94\x8c\x5model\x94\x8c\xe\x64\x65\x65pseek-flash\x94ub.)"
)

LEGACY_PICKLED_CONFIG = (
    b"[main_window]\n"
    rb"geometry=@ByteArray(\x1\xd9\xd0\xcb)" b"\n"
    + LEGACY_PICKLE_LINE
    + b'\ntarget_language=ru\ntarget_language_list="ar,de,en,ru"\n'
    b"\n[ocr_feature]\n" + LEGACY_PICKLE_LINE + b"\n"
)


@pytest.fixture(name="legacy_pickled_config")
def legacy_pickled_config_fixture():
    """An INI file PySide6 6.12 cannot read until it is sanitized."""
    return LEGACY_PICKLED_CONFIG

