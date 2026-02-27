"""
Diagnostics mixin — rotating file logger and 30-second performance sampler.

Log file
--------
``can_viewer_diag.log`` is written to:

* The project root directory when running from source.
* The directory that contains the ``.exe`` when running as a PyInstaller bundle.

Maximum size 5 MB with 2 rotating backups, UTF-8 encoded.

Usage
-----
All other mixins can call ``self._diag_log(message)`` to append a line.
``self._diag_open_log()`` opens the file in the OS default text viewer.
``self._diag_perf_sample()`` is called from the 200 ms stats-label timer and
flushes a snapshot to the log every 30 seconds.
"""
import logging
import logging.handlers
import os
import subprocess
import sys
import time
from tkinter import messagebox

# Resolve the project root at import time.
# __file__ is  can_viewer/mixins/diag.py → go up two levels.
_PKG_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


class DiagMixin:
    """Mixin that adds a rotating diagnostic log and live performance counters."""

    # ------------------------------------------------------- setup / teardown

    def _setup_diag(self) -> None:
        """Initialise the rotating log file.  Called once from ``CANViewer.__init__``.

        The sampling counters (``_diag_last_sample``, ``_diag_sample_msgs``,
        ``_diag_sample_drops``) are *always* set first so that callers never
        receive an ``AttributeError`` even if the file handler cannot be created.
        """
        # Always initialise counters — never leave them undefined.
        self._diag: logging.Logger | None = None
        self._diag_path: str | None = None
        self._diag_last_sample: float = time.monotonic()
        self._diag_sample_msgs: int = 0
        self._diag_sample_drops: int = 0

        try:
            if getattr(sys, "frozen", False):
                # PyInstaller bundle — write next to the .exe
                log_dir = os.path.dirname(os.path.abspath(sys.executable))
            else:
                log_dir = _PKG_ROOT

            self._diag_path = os.path.join(log_dir, "can_viewer_diag.log")

            logger = logging.getLogger("can_viewer.diag")
            logger.setLevel(logging.DEBUG)

            if not logger.handlers:          # avoid duplicate handlers on reload
                handler = logging.handlers.RotatingFileHandler(
                    self._diag_path,
                    maxBytes=5 * 1024 * 1024,   # 5 MB
                    backupCount=2,
                    encoding="utf-8",
                )
                handler.setFormatter(logging.Formatter(
                    "%(asctime)s %(levelname)-8s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                ))
                logger.addHandler(handler)

            self._diag = logger
            self._diag.info(
                "=== CAN Bus Viewer started  Python %s  pid=%d ===",
                sys.version.split()[0], os.getpid(),
            )
        except Exception:  # noqa: BLE001
            # Never crash the app because of a logging problem.
            self._diag = None

    # ------------------------------------------------------------------  write

    def _diag_log(self, msg: str, level: str = "info") -> None:
        """Write a single line to the diagnostic log (no-op if setup failed)."""
        if self._diag:
            getattr(self._diag, level, self._diag.info)(msg)

    # --------------------------------------------------------------- sampling

    def _diag_perf_sample(self) -> None:
        """Flush a performance snapshot to the log every 30 seconds.

        Called from ``_update_stats_labels`` (200 ms timer) so it piggy-backs
        on an existing timer without adding a new one.
        """
        now = time.monotonic()
        elapsed = now - self._diag_last_sample
        if elapsed < 30:
            return

        rate  = self._diag_sample_msgs / elapsed if elapsed else 0
        drops = self._diag_sample_drops
        qsize = self.message_queue.qsize()

        if self._diag:
            self._diag.info(
                "PERF: %.0f msg/s  drops_window=%d  total_drops=%d  "
                "queue=%d/%d  raw_rows=%d  sym_msgs=%d  highlights=%d",
                rate, drops, self._dropped_count,
                qsize, self.message_queue.maxsize,
                self._raw_tree_count, len(self._msg_iids),
                len(self._highlight_after_ids),
            )

        # Reset window counters.
        self._diag_sample_msgs = 0
        self._diag_sample_drops = 0
        self._diag_last_sample = now

    # ----------------------------------------------------------------- open UI

    def _diag_open_log(self) -> None:
        """Open the diagnostic log file in the OS default text viewer."""
        path = self._diag_path
        if not path or not os.path.exists(path):
            messagebox.showinfo(
                "Diagnostics",
                f"Log file not found:\n{path or '(not configured)'}\n\n"
                "The file is created automatically when the app starts logging.",
                parent=self.root,
            )
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)          # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as exc:
            messagebox.showerror(
                "Open Error",
                f"Could not open:\n{path}\n\n{exc}",
                parent=self.root,
            )
