import sys
import signal

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import Slot, QSettings

from .main_window import MainWindow
from .about_window import AboutWindow
from .signal_handling_app import SignalHandlingApp
from .__version__ import version


class App(SignalHandlingApp):
    signals_for_handle = [signal.SIGUSR1]

    def __init__(self, args):
        super().__init__(args)
        self.setQuitOnLastWindowClosed(False)

        self.setApplicationDisplayName("Barbaros")
        # OrganizationName конфликтует с OrganizationDomain
        self.setOrganizationDomain("io.github.frimn")
        self.setApplicationVersion(version)
        self.setApplicationName("barbaros")

        self.settings = QSettings(QSettings.Scope.UserScope)
        print(f"Settings filepath: {self.settings.fileName()}")

        self.tray = TrayIcon(self)
        self.main_window = MainWindow(app=self)
        self.about_window = AboutWindow()

    @Slot(int)
    def handle_signal_in_qt(self, signum: int):
        """Handle signal in Qt event loop context"""
        if signum == signal.SIGUSR1:
            self.process_translation_request()

    def process_translation_request(self):
        """Process the translation request"""

        # Now always use clipboard
        text = QApplication.clipboard().text()

        self.main_window.orig_text.setPlainText(text)
        self.main_window.show()
        self.main_window.raise_()  # Bring window to front
        self.main_window.activateWindow()
        # TODO: Refactor to extract translation mechanism to App class.
        self.main_window.translate_button.click()

    def switch_window(self):
        if not self.main_window.isVisible():
            self.main_window.show()
            self.main_window.raise_()
            self.main_window.activateWindow()
        else:
            self.main_window.hide()

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

        about_action = QAction("About", parent=self.icon)
        about_action.triggered.connect(self.on_about_activated)
        menu.addAction(about_action)

        exit_action = QAction("Exit", parent=self.icon)
        exit_action.triggered.connect(self.app.quit)
        menu.addAction(exit_action)

        return menu

    def on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """
        Обработка клика по иконке в трее.
        """
        ar = QSystemTrayIcon.ActivationReason

        if reason == ar.Trigger:
            # Левый клик
            self.app.switch_window()

    def on_about_activated(self):
        self.app.show_about_window()

def start_app():
    """ Normal start app """
    app = App(sys.argv)
    sys.exit(app.exec())


def open_window():
    """ Open main window of already running instance and start translation """
    import psutil
    import os

    app_name = "Barbaros"
    current_pid = os.getpid()

    print(f"{app_name.lower()=}")
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['pid'] == current_pid:
            continue  # Skip current process

        # Мы делаем сравнение по подстроке из-за того, что приложение может быть запущено в flatpak, там будет `/usr/bin/python /app/bin/barbaros`.
        print(proc.info['name'].lower())
        if app_name.lower() in proc.info['name'].lower():
            try:
                os.kill(proc.pid, signal.SIGUSR1)  # Send SIGUSR1 to open main window and start process of translation.
                print(f"Send SIGUSR1 to PID {proc.pid}")
                return True
            except (ProcessLookupError, PermissionError) as e:
                # Handle exceptions that might occur if the process is already terminated or access is denied.
                print(f"Error sending signal: {e}")
                pass

    print("No running instance found")
    return False


def main():
    # Позволяет остановить приложение из командной строки.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # try:
    if "--popup" in sys.argv:
        open_window()
    else:
        start_app()

    # except Exception as e:
    #     print(f"An error occurred: {e}", file=sys.stderr)
    #     sys.exit(1)


if __name__ == "__main__":
    main()
