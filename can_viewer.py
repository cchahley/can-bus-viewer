"""
Entry-point shim for CAN Bus Viewer.

This file exists so that:
  * ``python can_viewer.py`` still works as the run command.
  * PyInstaller's spec file (``can_viewer.spec``) does not need updating.
  * CI's ``py_compile can_viewer.py`` check still passes.

All application logic lives in the ``can_viewer/`` package.
"""
from can_viewer import main  # noqa: F401

if __name__ == "__main__":
    main()
