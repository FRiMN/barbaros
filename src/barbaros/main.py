from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction


class TrayIcon:
    def __init__(self, app: QApplication):
        self.app = app
        icon_img = QIcon("/usr/share/icons/desktop-base/128x128/emblems/emblem-debian-symbolic.png")
        self.icon = QSystemTrayIcon(icon_img)

        if not self.icon.isSystemTrayAvailable():
            raise Exception("System tray is not available")

        # Create context menu
        self.menu = QMenu()
        exit_action = QAction("Exit")
        exit_action.triggered.connect(self.app.quit)
        self.menu.addAction(exit_action)

        self.icon.setContextMenu(self.menu)

        self.icon.setVisible(True)


def get_tray():
    tray = QSystemTrayIcon(parent=app)
    tray.setIcon(QIcon("/usr/share/icons/desktop-base/128x128/emblems/emblem-debian-symbolic.png"))  

    menu = QMenu()
    exit_action = QAction("Exit")
    exit_action.triggered.connect(app.quit)
    menu.addAction(exit_action)

    tray.setContextMenu(menu)

    tray.setVisible(True)
    return tray, menu


def main():
    import sys
    import signal

    try:
        # Allow app to be terminated with Ctrl+C
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        app = QApplication(sys.argv)
        # tray_icon = TrayIcon(app)
        tray, menu = get_tray()

        sys.exit(app.exec())

    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
