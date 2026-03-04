"""High-throughput table model for raw CAN rows."""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor


class RawTableModel(QAbstractTableModel):
    """Ring-buffer model for the raw monitor table."""

    HEADERS = ["Timestamp", "Rel (s)", "Arb ID (hex)", "Frame", "DLC", "Data (hex)"]

    def __init__(self, max_rows: int = 1500) -> None:
        super().__init__()
        self._max_rows = max_rows
        self._rows: list[tuple[tuple[str, ...], bool]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, is_error = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole and is_error:
            return QColor("#a10d11")
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def append_rows(self, rows: Iterable[tuple[list[str], bool]]) -> None:
        """Append a batch of rows and refresh model."""
        batch = list(rows)
        if not batch:
            return
        incoming = [(tuple(values), is_error) for values, is_error in batch]
        total_after = len(self._rows) + len(incoming)
        if total_after <= self._max_rows:
            start = len(self._rows)
            end = start + len(incoming) - 1
            self.beginInsertRows(QModelIndex(), start, end)
            self._rows.extend(incoming)
            self.endInsertRows()
            return

        # Overflow case: keep newest rows. Reset is simpler and still cheaper
        # than per-row front removals under heavy traffic.
        keep = (self._rows + incoming)[-self._max_rows :]
        self.beginResetModel()
        self._rows = keep
        self.endResetModel()

    def clear(self) -> None:
        if not self._rows:
            return
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()
