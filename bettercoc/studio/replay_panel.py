from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .canvas import ImageCanvas
from .source import SessionSource
from .widgets import fill_table, format_score, make_table


class ReplayPanel(QWidget):
    def __init__(self, host, parent=None) -> None:
        super().__init__(parent)
        self.host = host
        self.canvas = ImageCanvas(self)
        self.canvas.selectable = False
        self.path_edit = QLineEdit(self)
        self.path_edit.setPlaceholderText("选择录制会话目录（含 manifest.json）")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        load = QPushButton("加载会话")
        load.clicked.connect(self._load_from_edit)
        self.frame_label = QLabel("帧: -")
        prev_button = QPushButton("上一帧")
        next_button = QPushButton("下一帧")
        prev_button.clicked.connect(lambda: self.host.step_frame(-1))
        next_button.clicked.connect(lambda: self.host.step_frame(1))
        self.replay_button = QPushButton("复现识别并对比")
        self.replay_button.clicked.connect(self.run_replay)
        self.summary = QLabel("未加载会话")

        top = QHBoxLayout()
        top.addWidget(QLabel("会话"))
        top.addWidget(self.path_edit, 1)
        top.addWidget(browse)
        top.addWidget(load)
        nav = QHBoxLayout()
        nav.addWidget(self.frame_label, 1)
        nav.addWidget(prev_button)
        nav.addWidget(next_button)
        nav.addWidget(self.replay_button)

        self.events_table = make_table(
            ["时间", "事件", "识别项", "状态", "得分", "错误码"]
        )
        self.mismatch_table = make_table(
            ["帧", "识别项", "录制状态", "回放状态", "录制得分", "回放得分"]
        )
        self.detail_label = QLabel("选择事件查看帧信息")
        self.detail_label.setWordWrap(True)

        right = QVBoxLayout()
        right.addWidget(QLabel("会话事件（当前帧）"))
        right.addWidget(self.events_table, 1)
        right.addWidget(QLabel("回放差异"))
        right.addWidget(self.mismatch_table, 1)
        right.addWidget(self.detail_label)
        right_widget = QWidget(self)
        right_widget.setLayout(right)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.canvas)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(nav)
        layout.addWidget(splitter, 1)
        self.setLayout(layout)
        self._events: list[dict] = []

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择录制会话")
        if path:
            self.path_edit.setText(path)
            self._load_from_edit()

    def _load_from_edit(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            return
        try:
            source = SessionSource(path)
        except Exception as exc:
            self.summary.setText(f"加载失败: {exc}")
            return
        self._events = source.events()
        self.summary.setText(
            f"会话 {source.session.run_id}：{source.frame_count()} 帧，"
            f"{len(self._events)} 个事件"
        )
        self.host.load_source_object(source)

    def set_source(self, source) -> None:
        if isinstance(source, SessionSource):
            self.path_edit.setText(source.description)
            self._events = source.events()
            self.summary.setText(
                f"会话 {source.session.run_id}：{source.frame_count()} 帧，"
                f"{len(self._events)} 个事件"
            )
        else:
            self._events = []
            self.summary.setText("当前数据源不是录制会话，可手动选择会话目录")

    def refresh_frame(self, index: int, frame) -> None:
        self.canvas.set_frame(frame)
        self.frame_label.setText(
            f"帧 {index + 1}/{self.host.frame_count()}  {frame.frame_id}"
        )
        self._fill_events(frame.frame_id)

    def _fill_events(self, frame_id: str) -> None:
        rows = []
        for event in self._events:
            if str(event.get("frame_id") or "") != frame_id:
                continue
            timestamp = event.get("timestamp")
            rows.append(
                [
                    "-"
                    if timestamp is None
                    else time.strftime("%H:%M:%S", time.localtime(float(timestamp))),
                    event.get("event_type", ""),
                    event.get("name", "-"),
                    event.get("status", "-"),
                    format_score(event.get("score")),
                    event.get("error_code", "-"),
                ]
            )
        fill_table(self.events_table, rows)

    def run_replay(self) -> None:
        source = self.host.source
        if not isinstance(source, SessionSource) or self.host.vision is None:
            self.summary.setText("先加载一个录制会话，并确保识别资源可用")
            return
        self.replay_button.setEnabled(False)
        self.summary.setText("回放中…")
        session = source.session
        self.host.submit(
            "replay-run",
            lambda: session.run(self.host.vision),
            self._on_replayed,
        )

    def _on_replayed(self, data) -> None:
        self.replay_button.setEnabled(True)
        summary = data["summary"]
        self.summary.setText(
            f"回放 {summary['frames']} 帧，检查 {summary['checks']}，"
            f"对比 {summary['comparisons']}，不一致 {summary['mismatches']}，"
            f"资源变更={data['assets_changed']}"
        )
        rows = [
            [
                item["frame_id"],
                item["name"],
                item["recorded_status"],
                item["replayed_status"],
                format_score(item["recorded_score"]),
                format_score(item["replayed_score"]),
            ]
            for item in data["mismatches"]
        ]
        fill_table(self.mismatch_table, rows)
        self.detail_label.setText(
            "资源指纹与录制时一致"
            if not data["assets_changed"]
            else "资源指纹与录制时不同，识别结果可能变化"
        )
