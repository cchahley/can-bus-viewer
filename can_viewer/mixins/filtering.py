"""
Filter mixin — multi-token message filter for the raw and symbolic trees.

The filter bar accepts space- or comma-separated tokens.  A message passes if
*any* token appears in the concatenated string ``"<arb_id> <data> <msg_name>"``.

Performance note
----------------
``_filter_tokens`` is a cached list updated only when the filter text changes.
``_show_message`` reads the cached list directly so no regex split happens in the
hot path (can be 10 000+ messages/second on a saturated bus).
"""
import re
import tkinter as tk


class FilterMixin:
    """Mixin that provides the filter bar logic for raw and symbolic trees."""

    def _clear_filter(self):
        """Clear the filter text field."""
        self._filter_var.set("")

    def _get_filter_tokens(self) -> list:
        """Split the filter text into lowercase tokens on space/comma boundaries."""
        raw = self._filter_var.get().strip()
        if not raw:
            return []
        return [t.lower() for t in re.split(r"[,\s]+", raw) if t]

    def _passes_filter(self, arb: str, data: str, msg_name: str, tokens: list) -> bool:
        """Return True if any token appears in the combined arb-id/data/name string."""
        haystack = f"{arb} {data} {msg_name}".lower()
        return any(t in haystack for t in tokens)

    def _on_filter_change(self):
        """Re-populate raw tree from buffer and apply sym-tree visibility.

        Called automatically via ``StringVar.trace_add`` whenever the filter
        entry changes.  Updates the cached token list first, then rebuilds the
        raw tree from the ring buffer and detaches/reattaches symbolic tree rows.
        """
        self._filter_tokens = self._get_filter_tokens()
        tokens = self._filter_tokens

        # ── Raw tree rebuild from buffer ──────────────────────────────────────
        self.tree.delete(*self.tree.get_children())
        self._raw_tree_count = 0
        for item in self._raw_buffer:
            ts, rel, arb, frame, dlc, data, is_error = item
            if is_error or not tokens or self._passes_filter(arb, data, "", tokens):
                tags = ("error",) if is_error else ()
                self._insert_raw_row((ts, rel, arb, frame, dlc, data), tags)
        if self.autoscroll_var.get():
            self.tree.yview_moveto(1.0)

        # ── Sym tree: detach/reattach message parent rows ─────────────────────
        for arb_id, msg_iid in self._msg_iids.items():
            msg_name = self.sym_tree.item(msg_iid)["text"]
            arb_hex  = f"0x{arb_id:x}"
            match = (not tokens
                     or self._passes_filter(arb_hex, "", msg_name, tokens))
            currently_shown = msg_iid in self.sym_tree.get_children("")
            if match and not currently_shown:
                self.sym_tree.reattach(msg_iid, "", tk.END)
            elif not match and currently_shown:
                self.sym_tree.detach(msg_iid)
