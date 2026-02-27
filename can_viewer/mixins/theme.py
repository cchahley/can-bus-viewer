"""
Theme mixin — dark / light mode toggle.

Applies a VS-Code-inspired dark colour palette using the ``clam`` ttk theme as
a base, overriding every widget class that tkinter exposes.  Restores the
original platform theme when switching back to light mode.

The "changed" highlight tag and the "error" tag colours are also updated so
they remain visible against both backgrounds.
"""
from tkinter import ttk


class ThemeMixin:
    """Mixin that switches the application between dark and light themes."""

    def _toggle_dark_mode(self):
        """Toggle the dark-mode flag and re-apply the theme."""
        self._dark_mode = not self._dark_mode
        self.btn_dark.config(
            text="Light Mode" if self._dark_mode else "Dark Mode")
        self._apply_theme()

    def _apply_theme(self):
        """Apply dark or light colour palette to all ttk widgets and canvases.

        Dark palette is based on VS Code's default dark theme colours.
        Calling this method is idempotent — it can safely be called again after
        new widgets are created.
        """
        style = ttk.Style()
        if self._dark_mode:
            try:
                style.theme_use("clam")
            except Exception:
                pass
            BG, FG      = "#1e1e1e", "#d4d4d4"
            FIELD       = "#2d2d30"
            SEL_BG      = "#264f78"
            TREE_BG     = "#252526"
            HEAD_BG     = "#2d2d30"
            BORDER      = "#3e3e42"
            style.configure(".",
                background=BG, foreground=FG,
                fieldbackground=FIELD,
                selectbackground=SEL_BG, selectforeground=FG,
                bordercolor=BORDER, troughcolor=FIELD)
            for w in ("TFrame", "TLabelframe"):
                style.configure(w, background=BG)
            style.configure("TLabelframe.Label", background=BG, foreground=FG)
            style.configure("TLabel",       background=BG, foreground=FG)
            style.configure("TCheckbutton", background=BG, foreground=FG)
            style.configure("TRadiobutton", background=BG, foreground=FG)
            style.configure("TButton",      background=BG, foreground=FG)
            style.map("TButton",
                      background=[("active", SEL_BG)],
                      foreground=[("active", "#ffffff")])
            style.configure("TEntry",
                fieldbackground=FIELD, foreground=FG, insertcolor=FG)
            style.configure("TCombobox",
                fieldbackground=FIELD, foreground=FG,
                selectbackground=SEL_BG, arrowcolor=FG)
            style.map("TCombobox",
                      fieldbackground=[("readonly", FIELD)],
                      foreground=[("readonly", FG)])
            style.configure("Treeview",
                background=TREE_BG, foreground=FG,
                fieldbackground=TREE_BG, rowheight=22)
            style.configure("Treeview.Heading",
                background=HEAD_BG, foreground=FG)
            style.map("Treeview",
                      background=[("selected", SEL_BG)],
                      foreground=[("selected", "#ffffff")])
            style.configure("TScrollbar",
                background=BG, troughcolor=FIELD, arrowcolor=FG)
            style.configure("TSeparator", background=BORDER)
            self.root.configure(background=BG)
            self._send_canvas.configure(background=FIELD)
            self._dbc_canvas.configure(background=FIELD)
            self.sym_tree.tag_configure("changed", background="#806600")
            self.tree.tag_configure("error", foreground="#ff6b6b")
        else:
            try:
                style.theme_use(self._original_theme)
            except Exception:
                pass
            self.root.configure(background="SystemButtonFace")
            self._send_canvas.configure(background="SystemButtonFace")
            self._dbc_canvas.configure(background="SystemButtonFace")
            self.sym_tree.tag_configure("changed", background="#ffff99")
            self.tree.tag_configure("error", foreground="red")
