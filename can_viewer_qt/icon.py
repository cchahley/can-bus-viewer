"""Qt app-icon helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resolve_app_icon_path() -> Path | None:
    """Return a usable .ico path if configured or present in app directories."""
    env_icon = os.getenv("CAN_VIEWER_ICON")
    if env_icon:
        path = Path(env_icon).expanduser()
        if path.is_file() and path.suffix.lower() == ".ico":
            return path

    base_dir = Path(__file__).resolve().parents[1]
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            base_dir = Path(meipass)

    candidates = [
        base_dir / "app.ico",
        base_dir / "icon.ico",
        base_dir / "can_viewer.ico",
        base_dir / "assets" / "app.ico",
        base_dir / "assets" / "icon.ico",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None

