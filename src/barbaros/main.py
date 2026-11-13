import signal
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .__version__ import version
from .about_window import AboutWindow
from .common import read_setting
from .i18n import load_translator, resolve_language
from .ipc import IPCService
from .main_window import MainWindow
from .settings_sanitize import (
    MemoryBackedSettings,
    prepare_settings_file,
    settings_file_path,
)


class App(QApplication):
    def __init__(self, args):
        super().__init__(args)
        self.setQuitOnLastWindowClosed(False)

        self.setApplicationDisplayName("Barbaros")
        # OrganizationName conflicts with OrganizationDomain
        self.setOrganizationDomain("io.github.frimn")
        self.setApplicationVersion(version)
        self.setApplicationName("barbaros")

        # BAR-01: PySide6 6.12 aborts the first read of each INI section that
        # still holds a pickled Python object.  The raw INI has to be cleaned
        # before the QSettings instance exists: QSettings snapshots the file in
        # its constructor, so a later rewrite would not be visible to it.
        # BAR-28: on a PySide6 that still unpickles (< 6.12) no on-disk
        # settings are read at all - the preparation step quarantines an
        # existing file (best effort) and the session uses in-memory settings.
        settings_path = settings_file_path()
        prepared = prepare_settings_file(settings_path)

        if prepared.removed:
            print(
                f"Settings: removed {prepared.removed} legacy pickled value(s); "
                f"backup next to {settings_path!s}"
            )
        if prepared.quarantined is not None:
            print(
                "Warning: this PySide6 executes pickled QSettings values, so the "
                "settings file was not read; it was moved to "
                f"{prepared.quarantined!s}. Settings are kept in memory."
            )
        if prepared.memory_backed:
            print(
                "Warning: settings are kept in memory for this session; "
                "preferences are not persisted by this PySide6 version (BAR-28)"
            )
        if prepared.removed is None and prepared.quarantined is None and not prepared.memory_backed:
            print(
                "Warning: could not sanitize the settings file; "
                "legacy values may remain"
            )

        if prepared.memory_backed:
            self.settings = MemoryBackedSettings()
        else:
            self.settings = QSettings(QSettings.Scope.UserScope)

        print(f"Settings filepath: {self.settings.fileName()}")
        if (
            not prepared.memory_backed
            and settings_path is not None
            and Path(self.settings.fileName()) != settings_path
        ):
            print(
                "Warning: QSettings path does not match the sanitized one: "
                f"{settings_path!s}"
            )

        # Install UI translator before any window is built so that all
        # ``tr()`` calls at construction time resolve to the chosen language.
        lang = resolve_language(read_setting(self.settings, "language"))
        self.translator = load_translator(lang)
        if self.translator is not None:
            self.installTranslator(self.translator)

        self.ipc = IPCService(app=self, as_server=True, as_client=False)

        # Windows and tray
        self.main_window = MainWindow(app=self)
        self.tray = TrayIcon(self)
        self.about_window = AboutWindow()

    def save_language(self, lang: str):
        """Persist the chosen UI language (applied on next launch)."""
        self.settings.setValue("language", lang)

        # Clean up threads on quit
        self.aboutToQuit.connect(self.cleanup)

    def process_translation_request(self):
        """Process the translation request"""

        # Now always use clipboard
        text = QApplication.clipboard().text()

        self.main_window.orig_text.setPlainText(text)
        self.raise_window()
        # TODO: Refactor to extract translation mechanism to App class.
        self.main_window.translate_button.click()

    def raise_window(self):
        self.main_window.show()
        self.main_window.raise_()   # Bring window to front
        self.main_window.activateWindow()

    def switch_window(self):
        if not self.main_window.isVisible():
            self.raise_window()
        else:
            self.main_window.hide()

    def cleanup(self):
        """Clean up resources before quit."""
        print("App cleanup: shutting down threads...")
        if hasattr(self, 'main_window') and hasattr(self.main_window, 'model_manager'):
            self.main_window.model_manager.shutdown()

    def show_about_window(self):
        self.about_window.show()
        self.about_window.raise_()
        self.about_window.activateWindow()


class TrayIcon:
    def __init__(self, app: App):
        from .resources_loader import Resource

        self.app = app
        self.icon = QSystemTrayIcon(QIcon(Resource.icon_app.value), toolTip=app.applicationDisplayName())

        if not self.icon.isSystemTrayAvailable():
            raise Exception("System tray is not available")

        self.icon.activated.connect(self.on_tray_icon_activated)

        self.menu = self.build_menu()
        self.icon.setContextMenu(self.menu)
        self.icon.setVisible(True)
        self.icon.show()

    def build_menu(self):
        # Parent is important in this place
        menu = QMenu()

        open_window = QAction(
            QCoreApplication.translate("Tray", "Open Window"), parent=self.icon
        )
        open_window.triggered.connect(self.app.raise_window)
        menu.addAction(open_window)

        about_action = QAction(
            QCoreApplication.translate("Tray", "About"), parent=self.icon
        )
        about_action.triggered.connect(self.on_about_activated)
        menu.addAction(about_action)

        exit_action = QAction(
            QCoreApplication.translate("Tray", "Exit"), parent=self.icon
        )
        exit_action.triggered.connect(self.app.quit)
        menu.addAction(exit_action)

        return menu

    def on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """
        Handle a click on the tray icon.
        """
        ar = QSystemTrayIcon.ActivationReason

        if reason == ar.Trigger:
            # Left click
            self.app.switch_window()

    def on_about_activated(self):
        self.app.show_about_window()


def start_app(open_main_window=False):
    """ Normal start app """
    app = App(sys.argv)
    if open_main_window:
        app.raise_window()
    sys.exit(app.exec())


def open_window():
    ipc = IPCService(as_client=True, as_server=False)
    ipc.send_popup_and_translate()


def main():
    # Allows stopping the application from the command line.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if "--popup" in sys.argv:
        open_window()
    else:
        start_app(open_main_window="--opened" in sys.argv)


if __name__ == "__main__":
    main()
