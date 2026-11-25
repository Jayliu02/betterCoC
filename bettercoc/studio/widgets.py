from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem

STATUS_COLORS = {
    "matched": QColor(70, 200, 120),
    "coordinate_only": QColor(230, 190, 70),
    "miss": QColor(190, 120, 120),
    "unknown": QColor(150, 150, 170),
    "true_positive": QColor(70, 200, 120),
    "false_negative": QColor(220, 120, 120),
    "false_positive": QColor(230, 160, 60),
    "true_negative": QColor(170, 175, 185),
}


def make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setSortingEnabled(False)
    return table


def set_cell(table: QTableWidget, row: int, column: int, value, color: QColor | None = None) -> None:
    text = "" if value is None else str(value)
    item = QTableWidgetItem(text)
    if color is not None:
        item.setForeground(color)
    table.setItem(row, column, item)


def fill_table(table: QTableWidget, rows: list[list], status_column: int | None = None) -> None:
    table.setRowCount(0)
    for values in rows:
        row = table.rowCount()
        table.insertRow(row)
        color = None
        if status_column is not None and status_column < len(values):
            color = STATUS_COLORS.get(str(values[status_column]))
        for column, value in enumerate(values):
            set_cell(table, row, column, value, color if column == status_column else None)
    table.resizeColumnsToContents()


def format_rect(rect) -> str:
    if rect is None:
        return "-"
    if hasattr(rect, "to_list"):
        return ",".join(str(value) for value in rect.to_list())
    return ",".join(str(value) for value in rect)


def format_score(score) -> str:
    return "-" if score is None else f"{float(score):.3f}"
