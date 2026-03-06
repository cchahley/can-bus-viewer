# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Qt CAN Bus Viewer executable."""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

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

# Include runtime data (Qt plugins/translations and package data) needed by the
# frozen app to start without missing-DLL/plugin errors on end-user machines.
datas += collect_data_files("PySide6")

binaries = []
# Pull package-shipped dynamic libraries so dependent native modules are present
# in dist even when PyInstaller does not auto-discover them.
for package_name in ("PySide6", "shiboken6", "can", "serial"):
    binaries += collect_dynamic_libs(package_name)

a = Analysis(
    ["can_viewer_qt.py"],
    pathex=[str(project_root)],
    binaries=binaries,
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
    a.binaries,
    a.datas,
    [],
    exclude_binaries=False,
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
