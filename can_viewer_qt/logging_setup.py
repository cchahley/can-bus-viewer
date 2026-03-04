"""Application logging setup for Qt CAN viewer."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QMessageBox


def _log_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d")
    return Path.cwd() / f"can_viewer_qt_{ts}.log"


def initialize_logging() -> Path:
    """Configure file logging and install a global exception hook."""
    log_path = _log_path()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
    logger = logging.getLogger("can_viewer_qt")
    logger.info("Logging initialized at %s", log_path)

    def _excepthook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        logger.exception("Uncaught exception", exc_info=(exc_type, exc, tb))
        try:
            QMessageBox.critical(
                None,
                "Unexpected Error",
                f"An unexpected error occurred.\n\n{exc}\n\nLog file:\n{log_path}",
            )
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook
    return log_path

