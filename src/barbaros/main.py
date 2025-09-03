import sys
import signal

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QSettings

from .main_window import MainWindow
from .about_window import AboutWindow
from .ipc import IPCService
from .__version__ import version


class App(QApplication):
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

        self.ipc = IPCService(app=self, as_server=True, as_client=False)

        self.tray = TrayIcon(self)
        self.main_window = MainWindow(app=self)
        self.about_window = AboutWindow()

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
    ipc = IPCService(as_client=True, as_server=False)
    ipc.send_popup_and_translate()


def main():
    # Позволяет остановить приложение из командной строки.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if "--popup" in sys.argv:
        open_window()
    else:
        start_app()


if __name__ == "__main__":
    main()
