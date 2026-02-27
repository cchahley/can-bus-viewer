"""
Plot mixin — real-time signal plot using matplotlib embedded in a tkinter Toplevel.

The plot window shows two panes side-by-side:
* **Left** — a multi-select Listbox populated with all numeric DBC signals in
  "MessageName.SignalName" format.
* **Right** — a matplotlib figure updated every 250 ms from the rolling sample
  buffers maintained by ``MessageDisplayMixin._decode_and_display``.

``matplotlib`` is an optional dependency.  If it is not installed the toolbar
button still appears but shows an informational message instead.
"""
import tkinter as tk
from tkinter import messagebox, ttk

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False


class PlotMixin:
    """Mixin that provides the real-time signal plot window."""

    def _open_plot_window(self):
        """Open (or raise) the signal plot Toplevel window.

        Creates the matplotlib figure and embeds it via ``FigureCanvasTkAgg``.
        A 250 ms ``after`` loop keeps the plot current while the window is open.
        """
        if not _MATPLOTLIB_AVAILABLE:
            messagebox.showinfo(
                "Signal Plot",
                "matplotlib is not installed.\n\nRun:  pip install matplotlib")
            return
        if self._plot_win and self._plot_win.winfo_exists():
            self._plot_win.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("Signal Plot")
        win.geometry("960x520")
        win.protocol("WM_DELETE_WINDOW",
                     lambda: (win.destroy(), setattr(self, "_plot_win", None)))
        self._plot_win = win

        # ── Left: signal selector ─────────────────────────────────────────────
        left = ttk.Frame(win, padding=4)
        left.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(left, text="DBC Signals (numeric only):").pack(anchor=tk.W)
        lb_frame = ttk.Frame(left)
        lb_frame.pack(fill=tk.BOTH, expand=True)
        self._plot_listbox = tk.Listbox(lb_frame, selectmode=tk.MULTIPLE,
                                        width=26, height=22, exportselection=False)
        lb_vsb = ttk.Scrollbar(lb_frame, orient=tk.VERTICAL,
                                command=self._plot_listbox.yview)
        self._plot_listbox.configure(yscrollcommand=lb_vsb.set)
        self._plot_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lb_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._populate_plot_listbox()
        ttk.Button(left, text="Plot Selected",
                   command=self._on_plot_selected).pack(fill=tk.X, pady=(4, 2))
        ttk.Button(left, text="Clear Plot",
                   command=self._clear_plot).pack(fill=tk.X)

        # ── Right: matplotlib chart ───────────────────────────────────────────
        right = ttk.Frame(win, padding=4)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fig = Figure(figsize=(7, 4.5), tight_layout=True)
        self._plot_ax = fig.add_subplot(111)
        self._plot_ax.set_xlabel("Sample index")
        self._plot_ax.set_ylabel("Value")
        self._plot_ax.grid(True)
        self._plot_canvas_widget = FigureCanvasTkAgg(fig, right)
        self._plot_canvas_widget.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._plot_canvas_widget.draw()
        self._plot_fig = fig

        self._schedule_plot_refresh()

    def _populate_plot_listbox(self):
        """Fill the signal listbox with all numeric (non-enum) signals from the DBC."""
        self._plot_listbox.delete(0, tk.END)
        if self.db:
            for msg in sorted(self.db.messages, key=lambda m: m.name):
                for sig in sorted(msg.signals, key=lambda s: s.name):
                    if not sig.choices:
                        self._plot_listbox.insert(
                            tk.END, f"{msg.name}.{sig.name}")

    def _on_plot_selected(self):
        """Update the active signal list from the current listbox selection."""
        self._plot_active_signals = [
            self._plot_listbox.get(i)
            for i in self._plot_listbox.curselection()]

    def _clear_plot(self):
        """Clear the active signal list and redraw a blank axes."""
        self._plot_active_signals = []
        if hasattr(self, "_plot_ax") and self._plot_ax:
            self._plot_ax.cla()
            self._plot_ax.set_xlabel("Sample index")
            self._plot_ax.set_ylabel("Value")
            self._plot_ax.grid(True)
            self._plot_canvas_widget.draw_idle()

    def _schedule_plot_refresh(self):
        """Schedule ``_do_plot_refresh`` every 250 ms while the plot window is open."""
        if self._plot_win and self._plot_win.winfo_exists():
            self._do_plot_refresh()
            self._plot_win.after(250, self._schedule_plot_refresh)

    def _do_plot_refresh(self):
        """Redraw the plot from the current sample buffers."""
        if not self._plot_active_signals:
            return
        ax = self._plot_ax
        ax.cla()
        ax.set_xlabel("Sample index")
        ax.set_ylabel("Value")
        ax.grid(True)
        for key in self._plot_active_signals:
            buf = self._plot_buffers.get(key)
            if buf and len(buf) > 1:
                ax.plot(list(buf), label=key.split(".")[-1], linewidth=1.5)
        ax.legend(loc="upper left", fontsize=8)
        self._plot_canvas_widget.draw_idle()
