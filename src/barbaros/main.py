import sys
import signal
import socket

from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu
)
from PySide6.QtGui import QIcon, QAction, QGuiApplication
from PySide6.QtCore import QObject, Signal, Slot, QSocketNotifier, QTimer

from .main_window import MainWindow


class App(QApplication):
    def __init__(self, args, name: str):
        super().__init__(args)
        self.setApplicationDisplayName(name)
        self.setQuitOnLastWindowClosed(False)

        self.tray = TrayIcon(self)
        self.main_window = MainWindow()
        # self.clipboard_listener = ClipboardListener(self)
        # self.switch_window()
        # self.switch_window()

        signal.signal(signal.SIGUSR1, self.on_signal_received)

    def switch_window(self):
        if not self.main_window.isVisible():
            print("show")
            self.main_window.show()
        else:
            print("hide")
            self.main_window.hide()

    def on_signal_received(self, signum, frame):
        print(f"Signal received: {signum}")
        # Read text from clipboard
        text = QApplication.clipboard().text()
        print(f"Received signal {signum}")

        self.main_window.orig_text.setPlainText(text)
        self.main_window.show()
        self.main_window.translate_button.click()


class TrayIcon:
    def __init__(self, app: QApplication):
        from .resources_loader import Resource

        self.app = app
        self.icon = QSystemTrayIcon(QIcon(Resource.icon_app.value), toolTip=app.applicationDisplayName())

        if not self.icon.isSystemTrayAvailable():
            raise Exception("System tray is not available")

        self.menu = self.build_menu()
        self.icon.setContextMenu(self.menu)

        self.icon.activated.connect(self.on_tray_icon_activated)

        self.icon.setVisible(True)
        self.icon.show()

    def build_menu(self):
        menu = QMenu()

        # Parent is important in this place
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


def start_app():
    """ Normal start app """
    # Allow app to be terminated with Ctrl+C
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = App(sys.argv, "Barbaros")
    sys.exit(app.exec())


def open_window():
    """ Open main window of already running instance or start new instance, then start translation """
    import psutil
    import os

    app_name = "Barbaros"
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'].lower() == app_name.lower():
            try:
                os.kill(proc.pid, signal.SIGUSR1)  # Send SIGUSR1 to open main window and start process of translation.
                print(f"Send to PID {proc.pid}")
            except (ProcessLookupError, PermissionError):
                # Handle exceptions that might occur if the process is already terminated or access is denied.
                pass

            break


def main():
    try:
        if "--popup" in sys.argv:
            sys.argv.remove("--popup")
            open_window()
        else:
            start_app()

    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
