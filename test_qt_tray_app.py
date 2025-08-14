import sys
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction

app = QApplication(sys.argv)

# Create tray icon
tray = QSystemTrayIcon()
tray.setIcon(QIcon("/usr/share/icons/desktop-base/128x128/emblems/emblem-debian-symbolic.png"))  # Replace with your icon path

# Create context menu
menu = QMenu()
exit_action = QAction("Exit")
exit_action.triggered.connect(app.quit)
menu.addAction(exit_action)

# Set context menu
tray.setContextMenu(menu)

# Show tray icon
tray.setVisible(True)

sys.exit(app.exec())