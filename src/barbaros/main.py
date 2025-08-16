from importlib.resources import path
import threading
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMainWindow, QLabel, QTextEdit, QVBoxLayout, QWidget, QPushButton
)
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QThread, Signal, QObject

from .translator import translate_text


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

        self.layout = self.build_layout()

        main_widget = QWidget()
        main_widget.setLayout(self.layout)

        self.setCentralWidget(main_widget)

    def set_widgets(self):
        self.orig_text = QTextEdit()
        self.translated_text = QTextEdit(readOnly=True)

        self.translate_button = QPushButton()
        self.translate_button.setText("Translate")
        self.translate_button.clicked.connect(self.handle_translate_button)

    def build_layout(self):
        self.set_widgets()

        layout = QVBoxLayout()
        layout.addWidget(self.orig_text)
        layout.addWidget(self.translate_button)
        layout.addWidget(self.translated_text)

        return layout

    def translate(self):
        text_to_translate = self.orig_text.toPlainText()
        self.translated_text.clear()
        self.translated_text.setText("Translating...")
        
        # Run translation in a separate thread
        self.translation_thread = QThread(parent=self)
        self.worker = TranslationWorker(text_to_translate)
        self.worker.moveToThread(self.translation_thread)

        self.worker.finished.connect(self.on_translation_finished)
        self.worker.finished.connect(self.translation_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.translation_thread.finished.connect(self.translation_thread.deleteLater)
        self.translation_thread.started.connect(self.worker.run)

        self.translation_thread.start()

    def on_translation_finished(self, translated_text):
        self.translated_text.setText(translated_text)
        self.translate_button.setDisabled(False)

    def handle_translate_button(self):
        self.translate_button.setDisabled(True)
        self.translate()


class TranslationWorker(QObject):
    finished = Signal(str)  # Worker is finished and starts to close (close the main application).
    error = Signal(str)  # Worker encountered an error.

    def __init__(self, text_to_translate):
        super().__init__()
        self.text_to_translate = text_to_translate

    def run(self):
        """Run in thread."""
        print("Starting translation...")
        translated = translate_text(self.text_to_translate)
        print("...done")
        self.finished.emit(translated)


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
