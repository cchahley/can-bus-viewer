"""
Reader mixin — background bus polling and GUI-side queue draining.

Responsibilities
----------------
* ``_reader``              — background daemon thread: calls ``bus.recv`` in a loop
                             and puts messages into the bounded queue using
                             ``put_nowait`` so it never blocks.  Transient
                             ``CanError`` exceptions are retried up to 5 times
                             (with a brief sleep) before the connection is torn
                             down, which prevents single bus-glitches from causing
                             a full disconnect.
* ``_poll_queue``          — GUI-side scheduler (10 ms ``root.after`` loop): drains
                             up to ``_MAX_PER_CYCLE`` items per tick so the event
                             loop is never starved on a high-traffic bus.
* ``_insert_raw_row``      — inserts a row into the raw Treeview, evicting the
                             oldest row once the cap (``_MAX_RAW_ROWS``) is reached.
                             Uses ``_raw_iid_deque`` for O(1) oldest-row lookup
                             instead of calling ``tree.get_children()`` (which was
                             O(n) and built a full tuple on every insert).
* ``_update_stats_labels`` — 200 ms periodic timer that refreshes the message/error
                             /dropped-count labels and triggers ``_diag_perf_sample``.
"""
import queue
import time
import tkinter as tk

import can


class ReaderMixin:
    """Mixin that owns the background reader thread and the GUI poll loop."""

    # ------------------------------------------------------- background reader

    def _reader(self):
        """Receive CAN messages on the background thread and enqueue them.

        Runs until ``self.running`` is cleared or a fatal bus error occurs.

        Transient ``CanError`` exceptions (e.g. brief USB hiccup, adapter
        buffer overflow) are retried up to 5 consecutive times before the
        thread gives up and signals a disconnect.  Each retry waits 50 ms.
        Non-CAN exceptions are always treated as fatal.

        Uses ``put_nowait`` so this thread never blocks; full-queue drops are
        counted in ``self._dropped_count`` for display in the diagnostics log.
        """
        consecutive_errors = 0
        while self.running and self.bus:
            try:
                msg = self.bus.recv(timeout=0.1)
                if msg is not None:
                    consecutive_errors = 0      # reset on a good receive
                    try:
                        self.message_queue.put_nowait(msg)
                    except queue.Full:
                        self._dropped_count += 1
                        self._diag_sample_drops += 1
                        # Log every 100th drop to avoid flooding the diag file.
                        if self._dropped_count % 100 == 1:
                            self._diag_log(
                                f"Queue full — msg dropped "
                                f"(total dropped: {self._dropped_count})",
                                "warning",
                            )
            except can.CanError as exc:
                consecutive_errors += 1
                self._diag_log(
                    f"CanError #{consecutive_errors}: {exc}", "warning")
                if consecutive_errors >= 5:
                    # Five consecutive hardware errors — give up and disconnect.
                    self._diag_log(
                        "5 consecutive CanErrors — triggering disconnect", "error")
                    try:
                        self.message_queue.put_nowait(("error", str(exc)))
                    except queue.Full:
                        pass
                    break
                time.sleep(0.05)    # brief pause before retrying
            except Exception as exc:
                self._diag_log(f"Reader fatal exception: {exc}", "error")
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
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return

        error_msg = None
        processed = 0
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
                processed += 1

        # Accumulate for the 30 s performance sample.
        self._diag_sample_msgs += processed

        if error_msg:
            self._diag_log(f"CAN error (reader thread): {error_msg}", "error")
            self.bar_var.set(f"CAN Error: {error_msg}")
        if self.autoscroll_var.get():
            self.tree.yview_moveto(1.0)
        self.root.after(10, self._poll_queue)

    def _insert_raw_row(self, values, tags=()):
        """Insert a row into the raw tree, evicting the oldest when over the cap.

        Uses ``_raw_iid_deque`` for O(1) oldest-row lookup.  Previously this
        called ``tree.get_children()`` on every insert, which built a tuple of
        all 2 000 iids each time — a significant hot-path cost on busy buses.
        """
        if self._raw_tree_count >= self._MAX_RAW_ROWS:
            if self._raw_iid_deque:
                oldest = self._raw_iid_deque.popleft()
                try:
                    self.tree.delete(oldest)
                except Exception:
                    pass          # iid may have been removed by a _clear()
                self._raw_tree_count -= 1
        iid = self.tree.insert("", tk.END, values=values, tags=tags)
        self._raw_iid_deque.append(iid)
        self._raw_tree_count += 1

    def _update_stats_labels(self):
        """Refresh message/error/dropped counters every 200 ms.

        Guards against the root window being destroyed during shutdown so the
        ``after`` loop does not generate spurious ``TclError`` exceptions.
        """
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return

        self.count_var.set(f"Messages: {self.message_count}")
        self.error_var.set(f"Errors: {self.error_count}")
        self._drop_var.set(
            f"Dropped: {self._dropped_count:,}" if self._dropped_count else "")
        self._diag_perf_sample()
        self.root.after(200, self._update_stats_labels)
