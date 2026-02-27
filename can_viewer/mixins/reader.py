"""
Reader mixin — background bus polling and GUI-side queue draining.

Responsibilities
----------------
* ``_reader``              — background daemon thread: calls ``bus.recv`` in a loop
                             and puts messages (or error tuples) into the bounded queue
                             using ``put_nowait`` so it never blocks.
* ``_poll_queue``          — GUI-side scheduler (10 ms ``root.after`` loop): drains up
                             to ``_MAX_PER_CYCLE`` items per tick to keep the event loop
                             responsive on saturated buses.
* ``_insert_raw_row``      — inserts a row into the raw Treeview, evicting the oldest
                             row once the cap (``_MAX_RAW_ROWS``) is reached.
* ``_update_stats_labels`` — 200 ms periodic timer that refreshes the message/error
                             count labels without calling ``StringVar.set`` on every
                             single message.
"""
import queue
import tkinter as tk

import can


class ReaderMixin:
    """Mixin that owns the background reader thread and the GUI poll loop."""

    # ------------------------------------------------------- background reader

    def _reader(self):
        """Receive CAN messages on the background thread and enqueue them.

        Runs until ``self.running`` is cleared or the bus raises an exception.
        Uses ``put_nowait`` with a silent drop on ``queue.Full`` so this thread
        never blocks — the GUI will catch up when it can.
        """
        while self.running and self.bus:
            try:
                msg = self.bus.recv(timeout=0.1)
                if msg is not None:
                    try:
                        self.message_queue.put_nowait(msg)
                    except queue.Full:
                        pass  # drop message; GUI is processing too slowly
            except can.CanError as exc:
                try:
                    self.message_queue.put_nowait(("error", str(exc)))
                except queue.Full:
                    pass
                break
            except Exception as exc:
                try:
                    self.message_queue.put_nowait(("error", str(exc)))
                except queue.Full:
                    pass
                break

    # -------------------------------------------------- queue → GUI (tkinter)

    def _poll_queue(self):
        """Drain the message queue and update the GUI (called every 10 ms).

        Processes at most ``_MAX_PER_CYCLE`` messages per call so that the
        tkinter event loop is never starved on a high-traffic bus.

        CAN errors are written to the status bar instead of showing a modal
        dialog, which previously caused re-entrant popup loops.
        """
        error_msg = None
        for _ in range(self._MAX_PER_CYCLE):
            try:
                item = self.message_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, tuple) and item[0] == "error":
                error_msg = item[1]
                self._disconnect()
                break
            else:
                self._show_message(item)
        if error_msg:
            self.bar_var.set(f"CAN Error: {error_msg}")
        if self.autoscroll_var.get():
            self.tree.yview_moveto(1.0)
        self.root.after(10, self._poll_queue)

    def _insert_raw_row(self, values, tags=()):
        """Insert a row into the raw tree, evicting the oldest when over the cap."""
        if self._raw_tree_count >= self._MAX_RAW_ROWS:
            children = self.tree.get_children()
            if children:
                self.tree.delete(children[0])
                self._raw_tree_count -= 1
        self.tree.insert("", tk.END, values=values, tags=tags)
        self._raw_tree_count += 1

    def _update_stats_labels(self):
        """Refresh message/error counters in the toolbar — runs every 200 ms."""
        self.count_var.set(f"Messages: {self.message_count}")
        self.error_var.set(f"Errors: {self.error_count}")
        self.root.after(200, self._update_stats_labels)
