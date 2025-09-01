from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt
from toml import load

from .__version__ import version

class AboutWindow(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("About Barbaros")

        self.version = version
        self.repository_url = self.get_repo_url()

        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()

        version_label = QLabel(f"Version: {self.version}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        repo_label = QLabel(f"<a href='{self.repository_url}'>Source code on GitHub</a>")
        repo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        repo_label.setOpenExternalLinks(True)
        layout.addWidget(repo_label)

        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.close)
        layout.addWidget(ok_button)

        self.setLayout(layout)
        self.adjustSize()

    def get_repo_url(self) -> str:
        with open("./pyproject.toml", 'r') as f:
            pyproject_data = load(f)
        return pyproject_data["project"]["urls"]["Homepage"]
