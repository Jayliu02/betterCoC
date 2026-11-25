from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .widgets import fill_table, format_score, make_table


class LogPanel(QWidget):
    KINDS = ("全部", "识别", "错误", "采集", "状态")

    def __init__(self, host, parent=None) -> None:
        super().__init__(parent)
        self.host = host
        self._events: list[dict] = []
        self.kind_box = QComboBox(self)
        self.kind_box.addItems(self.KINDS)
        self.kind_box.currentIndexChanged.connect(lambda _: self._fill())
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("按识别项、帧 ID 或错误码过滤")
        self.search_edit.textChanged.connect(lambda _: self._fill())
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.reload)
        export = QPushButton("导出诊断")
        export.clicked.connect(self.export)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("类型"))
        controls.addWidget(self.kind_box)
        controls.addWidget(self.search_edit, 1)
        controls.addWidget(refresh)
        controls.addWidget(export)
        self.summary = QLabel("没有事件")
        self.table = make_table(
            ["时间", "事件", "帧", "识别项", "状态", "得分", "错误码", "消息"]
        )
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        self.setLayout(layout)

    def set_source(self, source) -> None:
        self._events = [] if source is None else list(source.events())
        self.reload()

    def refresh_frame(self, index: int, frame) -> None:
        return None

    def reload(self) -> None:
        self._fill()

    def _matches(self, event: dict) -> bool:
        kind = self.kind_box.currentText()
        event_type = str(event.get("event_type") or "")
        if kind == "识别" and event_type != "recognition":
            return False
        if kind == "错误" and not event.get("error_code"):
            return False
        if kind == "采集" and event_type != "capture":
            return False
        if kind == "状态" and event_type != "state":
            return False
        needle = self.search_edit.text().strip().lower()
        if not needle:
            return True
        haystack = " ".join(
            str(event.get(key) or "")
            for key in ("name", "frame_id", "error_code", "message", "status")
        ).lower()
        return needle in haystack

    def _fill(self) -> None:
        rows = []
        for event in self._events:
            if not self._matches(event):
                continue
            timestamp = event.get("timestamp")
            rows.append(
                [
                    "" if timestamp is None else f"{float(timestamp):.3f}",
                    event.get("event_type", ""),
                    event.get("frame_id", "-"),
                    event.get("name", "-"),
                    event.get("status", "-"),
                    format_score(event.get("score")),
                    event.get("error_code", "-"),
                    event.get("message", ""),
                ]
            )
        fill_table(self.table, rows)
        errors = sum(1 for event in self._events if event.get("error_code"))
        self.summary.setText(f"共 {len(self._events)} 个事件，其中 {errors} 个带错误码")

    def export(self) -> None:
        default = str(Path(self.host.workspace) / "events-export.jsonl")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出诊断事件", default, "JSONL (*.jsonl);;所有文件 (*)"
        )
        if not path:
            return
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for event in self._events:
                if self._matches(event):
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.host.set_status(f"已导出 {target}")
