"""Application bootstrap for the PySide6 preview."""

from __future__ import annotations

import sys
import logging
import platform
import ctypes

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app_version import __version__

from .icon import resolve_app_icon_path
from .logging_setup import initialize_logging
from .main_window import CANViewerQtMainWindow
from .theme import LIGHT_STYLESHEET


def main() -> None:
    """Launch the Qt preview app."""
    log_path = initialize_logging()
    logger = logging.getLogger("can_viewer_qt")
    if platform.system() == "Windows":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"canbusviewer.qt.{__version__}"
            )
        except Exception:
            logger.exception("Failed setting Windows AppUserModelID")
    app = QApplication(sys.argv)
    app.setApplicationName(f"CAN Bus Viewer {__version__}")
    app.setStyleSheet(LIGHT_STYLESHEET)
    icon_path = resolve_app_icon_path()
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))
    win = CANViewerQtMainWindow()
    if icon_path is not None:
        win.setWindowIcon(QIcon(str(icon_path)))
    logger.info("Application started. log_path=%s", log_path)
    win.show()
    sys.exit(app.exec())
