"""Styling helpers for the Qt preview UI."""

LIGHT_STYLESHEET = """
QMainWindow {
    background: #f3f5f8;
}

QWidget {
    font-family: "Segoe UI";
    font-size: 10pt;
    color: #17202a;
}

QTabWidget::pane {
    border: 1px solid #c8d0dc;
    border-radius: 8px;
    background: #ffffff;
}

QTabBar::tab {
    background: #e8edf5;
    border: 1px solid #c8d0dc;
    border-bottom: none;
    padding: 8px 14px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}

QTabBar::tab:selected {
    background: #ffffff;
    font-weight: 600;
}

QGroupBox {
    border: 1px solid #d6dde8;
    border-radius: 8px;
    margin-top: 8px;
    background: #ffffff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px 0 4px;
    color: #44556a;
}

QComboBox {
    border: 1px solid #b8c5d7;
    border-radius: 6px;
    padding: 5px 8px;
    background: #ffffff;
    color: #17202a;
    selection-background-color: #d9e8fb;
    selection-color: #10233b;
}

QComboBox:disabled {
    background: #eef2f8;
    color: #6d7e91;
    border-color: #d4dce8;
}

QComboBox QAbstractItemView {
    background: #ffffff;
    color: #17202a;
    selection-background-color: #d9e8fb;
    selection-color: #10233b;
    outline: 0;
    border: 1px solid #b8c5d7;
}

QComboBox QAbstractItemView::item:disabled {
    color: #7a8da3;
    background: #f2f5fa;
}

QLineEdit {
    border: 1px solid #b8c5d7;
    border-radius: 6px;
    padding: 5px 8px;
    background: #ffffff;
    color: #17202a;
    selection-background-color: #d9e8fb;
    selection-color: #10233b;
}

QLineEdit:disabled {
    background: #eef2f8;
    color: #6d7e91;
    border-color: #d4dce8;
}

QTableWidget,
QTableView,
QTreeWidget {
    background: #ffffff;
    alternate-background-color: #f7faff;
    color: #17202a;
    border: 1px solid #c9d3e0;
    gridline-color: #e1e7f0;
    selection-background-color: #d9e8fb;
    selection-color: #10233b;
}

QTableWidget::item,
QTableView::item,
QTreeWidget::item {
    background: #ffffff;
    color: #17202a;
}

QTextEdit,
QListWidget {
    background: #ffffff;
    color: #17202a;
    border: 1px solid #c9d3e0;
    selection-background-color: #d9e8fb;
    selection-color: #10233b;
}

QTextEdit QAbstractScrollArea,
QListWidget QAbstractScrollArea {
    background: #ffffff;
}

QHeaderView::section {
    background: #eaf0f8;
    color: #1f2f44;
    border: 1px solid #d0d9e6;
    padding: 4px 6px;
}

QPushButton {
    border: 1px solid #8ca2be;
    background: #f7f9fd;
    border-radius: 6px;
    padding: 6px 12px;
}

QPushButton:hover {
    background: #ebf1fb;
}

QPushButton#primaryButton {
    background: #145da0;
    color: #ffffff;
    border-color: #145da0;
}

QPushButton#primaryButton:hover {
    background: #0f4f8b;
}

QStatusBar {
    background: #e9eef5;
    border-top: 1px solid #c8d0dc;
}

QDialog,
QMessageBox {
    background: #ffffff;
    color: #17202a;
}

QMessageBox QLabel {
    color: #17202a;
    background: #ffffff;
}
"""
