"""Shared test configuration.

Qt GUI tests must be able to create a QApplication without a display (CI,
headless runs). The offscreen platform keeps rendering tests deterministic;
an explicitly configured QT_QPA_PLATFORM still wins.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
