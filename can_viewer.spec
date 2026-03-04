# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Qt CAN Bus Viewer executable."""

from __future__ import annotations

import os
from pathlib import Path


project_root = Path(SPECPATH)

icon_candidates = []
env_icon = os.getenv("CAN_VIEWER_ICON")
if env_icon:
    icon_candidates.append(Path(env_icon).expanduser())
icon_candidates.extend(
    [
        project_root / "app.ico",
        project_root / "icon.ico",
        project_root / "can_viewer.ico",
        project_root / "assets" / "app.ico",
        project_root / "assets" / "icon.ico",
    ]
)

icon_path = next(
    (
        str(path)
        for path in icon_candidates
        if path.is_file() and path.suffix.lower() == ".ico"
    ),
    None,
)

datas = []
if icon_path:
    datas.append((icon_path, "."))

a = Analysis(
    ["can_viewer_qt.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "can.interfaces.pcan.pcan",
        "can.interfaces.vector.canlib",
        "can.interfaces.slcan",
        "serial",
        "serial.tools.list_ports",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="can_viewer_qt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="can_viewer_qt",
)
