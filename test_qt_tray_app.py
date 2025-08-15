import sys
import signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction

signal.signal(signal.SIGINT, signal.SIG_DFL)

class MainApp(QApplication):
    def __init__(self, args):
        super().__init__(args)

        icon_path = "/usr/share/icons/desktop-base/128x128/emblems/emblem-debian-symbolic.png"
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(QIcon(icon_path))
        
        menu = QMenu()

        # Parent is important in this place
        exit_action = QAction("Exit", parent=self.tray)
        exit_action.triggered.connect(self.quit)

        menu.addAction(exit_action)
        
        self.tray.setContextMenu(menu)
        menu.setVisible(True)

        self.tray.setVisible(True)


app = MainApp(sys.argv)
sys.exit(app.exec())