from importlib.resources import path

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction


class App(QApplication):
    def __init__(self, args, name: str):
        super().__init__(args)
        self.setApplicationDisplayName(name)

        self.tray = TrayIcon(self)


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

        self.icon.setVisible(True)

    def build_menu(self):
        menu = QMenu()

        # Parent is important in this place
        exit_action = QAction("Exit", parent=self.icon)
        exit_action.triggered.connect(self.app.quit)
        menu.addAction(exit_action)

        return menu


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
