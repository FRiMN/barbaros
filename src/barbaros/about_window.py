from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt

from .__version__ import version, __version_tuple__

class AboutWindow(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle(self.tr("About Barbaros"))

        self.version = version
        self.year = __version_tuple__[0]
        self.repository_url = "https://github.com/FRiMN/barbaros/"

        self.initUI()

    def initUI(self):
        from .resources_loader import Resource

        align_center = Qt.AlignmentFlag.AlignCenter

        layout = QVBoxLayout()

        icon_label = QLabel()
        icon_pixmap = Resource.icon_app.value
        icon_label.setPixmap(icon_pixmap.scaledToWidth(128, Qt.TransformationMode.SmoothTransformation))
        icon_label.setAlignment(align_center)
        layout.addWidget(icon_label)

        app_name = QLabel(self.tr("Barbaros"))
        app_name.setAlignment(align_center)
        app_name.setFont(QFont("Arial", 24))
        layout.addWidget(app_name)

        description_label = QLabel(self.tr("AI translation tool"))
        description_label.setAlignment(align_center)
        layout.addWidget(description_label)

        layout.addSpacing(20)

        version_label = QLabel(self.tr("Version: %1").replace("%1", self.version))
        version_label.setAlignment(align_center)
        layout.addWidget(version_label)

        repo_label = QLabel(
            self.tr("<a href='%1'>Source code on GitHub</a>").replace("%1", self.repository_url)
        )
        repo_label.setAlignment(align_center)
        repo_label.setOpenExternalLinks(True)
        layout.addWidget(repo_label)

        license_label = QLabel(self.tr("License: MIT"))
        license_label.setAlignment(align_center)
        layout.addWidget(license_label)

        copyright_label = QLabel(
            self.tr("Copyright © %1 Nikolay Volkov").replace("%1", str(self.year))
        )
        copyright_label.setAlignment(align_center)
        layout.addWidget(copyright_label)

        layout.addSpacing(20)

        ok_button = QPushButton(self.tr("OK"))
        ok_button.clicked.connect(self.close)
        layout.addWidget(ok_button)

        self.setLayout(layout)
        self.adjustSize()
