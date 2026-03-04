"""Application bootstrap for the PySide6 preview."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import CANViewerQtMainWindow
from .theme import LIGHT_STYLESHEET


def main() -> None:
    """Launch the Qt preview app."""
    app = QApplication(sys.argv)
    app.setApplicationName("CAN Bus Viewer Qt Preview")
    app.setStyleSheet(LIGHT_STYLESHEET)
    win = CANViewerQtMainWindow()
    win.show()
    sys.exit(app.exec())
