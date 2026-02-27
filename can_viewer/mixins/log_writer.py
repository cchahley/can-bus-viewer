"""
Logging mixin — start and stop CAN trace logging to CSV or BLF files.

Responsibilities
----------------
* ``_toggle_logging`` — start logging if idle, stop if active.
* ``_start_logging``  — prompt for a file, create a CSV writer or a BLF writer,
                        write the CSV header row, and update the UI.
* ``_stop_logging``   — flush and close the writer/file, reset state, update the UI.

The actual per-message write happens in ``MessageDisplayMixin._show_message`` which
has access to each message as it arrives.
"""
import csv
import tkinter as tk
from tkinter import filedialog, messagebox

import can


class LoggingMixin:
    """Mixin that manages writing received CAN messages to a file."""

    def _toggle_logging(self):
        """Start logging if not active; stop if currently logging."""
        if self.log_writer is None:
            self._start_logging()
        else:
            self._stop_logging()

    def _start_logging(self):
        """Prompt for a file path and begin writing received messages.

        Supports two formats:
        * **CSV** — plain text; every row has Timestamp, Arb ID, Frame, DLC, Data.
        * **BLF** — Vector Binary Logging Format; decoded by CANalyzer/CANdb++.
        """
        filename = filedialog.asksaveasfilename(
            title="Save CAN Trace",
            filetypes=[("CSV files", "*.csv"), ("BLF files", "*.blf")],
            defaultextension=".csv",
        )
        if not filename:
            return
        try:
            if filename.lower().endswith(".blf"):
                self.log_writer = can.BLFWriter(filename)
                self.log_format = "blf"
            else:
                self.log_file = open(filename, "w", newline="")
                self.log_writer = csv.writer(self.log_file)
                self.log_writer.writerow(["Timestamp", "Arb ID", "Frame", "DLC", "Data"])
                self.log_format = "csv"
        except Exception as exc:
            messagebox.showerror("Log Error", str(exc))
            return
        self.btn_log.config(text="Stop Log")
        self.bar_var.set(f"Logging to: {filename}")

    def _stop_logging(self):
        """Flush and close the current log writer."""
        try:
            if self.log_format == "blf" and self.log_writer:
                self.log_writer.stop()
            elif self.log_file:
                self.log_file.close()
        except Exception:
            pass
        self.log_writer = None
        self.log_file = None
        self.log_format = None
        self.btn_log.config(text="Start Log")
        self.bar_var.set("Log saved")
