from importlib.resources import path

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMainWindow, QLabel
from PySide6.QtGui import QIcon, QAction


class App(QApplication):
    def __init__(self, args, name: str):
        super().__init__(args)
        self.setApplicationDisplayName(name)
        self.setQuitOnLastWindowClosed(False)

        self.tray = TrayIcon(self)
        self.main_window = MainWindow()

    def show_window(self):
        self.main_window.show()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Main Window")
        self.setGeometry(100, 100, 400, 300)
        self.setCentralWidget(QLabel("This is the main window"))


class TrayIcon:
    def __init__(self, app: QApplication):
        self.app = app

        with path('barbaros.resources.icons', 'icon3.png') as icon_path:
            icon_img = QIcon(str(icon_path.absolute()))
        self.icon = QSystemTrayIcon(icon_img, toolTip=app.applicationDisplayName())

        if not self.icon.isSystemTrayAvailable():
            raise Exception("System tray is not available")

        self.menu = self.build_menu()
        self.icon.setContextMenu(self.menu)

        self.icon.activated.connect(self.on_tray_icon_activated)

        self.icon.setVisible(True)


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
            self.app.show_window()


def main():
    import sys
    import signal

    try:
        # Allow app to be terminated with Ctrl+C
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        app = App(sys.argv, "Barbaros")
        sys.exit(app.exec())

    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
