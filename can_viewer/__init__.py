"""
CAN Bus Viewer — a GUI application for monitoring, decoding, and sending CAN messages.

Public surface
--------------
CANViewer
    The main application class.  Instantiate it with a ``tk.Tk`` root window.
main
    Convenience entry point: creates the root window, instantiates ``CANViewer``,
    and runs the tkinter main loop.

Typical usage::

    from can_viewer import main
    main()

Or for embedding in a larger application::

    import tkinter as tk
    from can_viewer import CANViewer

    root = tk.Tk()
    app = CANViewer(root)
    root.protocol("WM_DELETE_WINDOW", app._on_close)
    root.mainloop()
"""

from .app import CANViewer

__all__ = ["CANViewer", "main"]


def main() -> None:
    """Launch the CAN Bus Viewer application."""
    import tkinter as tk

    root = tk.Tk()
    app = CANViewer(root)
    root.protocol("WM_DELETE_WINDOW", app._on_close)
    root.mainloop()
