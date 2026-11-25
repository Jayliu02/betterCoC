from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .canvas import ImageCanvas, Overlay
from .recognition import RecognitionRow, recognize_frame
from .widgets import fill_table, format_rect, format_score, make_table

STATUS_COLORS = {
    "matched": (70, 200, 120),
    "coordinate_only": (230, 190, 70),
    "miss": (180, 110, 110),
    "unknown": (150, 150, 170),
}


class VisionPanel(QWidget):
    def __init__(self, host, parent=None) -> None:
        super().__init__(parent)
        self.host = host
        self._rows: list[RecognitionRow] = []
        self._index = 0

        self.canvas = ImageCanvas(self)
        self.canvas.hoverChanged.connect(self._on_hover)

        left = QVBoxLayout()
        self.frame_label = QLabel("帧: -")
        left.addWidget(self.frame_label)
        nav = QHBoxLayout()
        self.prev_button = QPushButton("上一帧")
        self.next_button = QPushButton("下一帧")
        self.prev_button.clicked.connect(lambda: self.host.step_frame(-1))
        self.next_button.clicked.connect(lambda: self.host.step_frame(1))
        nav.addWidget(self.prev_button)
        nav.addWidget(self.next_button)
        left.addLayout(nav)
        left.addWidget(QLabel("识别项"))
        self.asset_list = QListWidget(self)
        self.asset_list.setMinimumWidth(220)
        left.addWidget(self.asset_list, 1)
        self.show_roi = QCheckBox("显示 ROI")
        self.show_roi.setChecked(True)
        self.show_roi.stateChanged.connect(lambda _: self._apply_overlays())
        left.addWidget(self.show_roi)
        left_widget = QWidget(self)
        left_widget.setLayout(left)

        right = QVBoxLayout()
        controls = QHBoxLayout()
        self.recognize_button = QPushButton("识别当前帧")
        self.recognize_button.clicked.connect(self.recognize)
        controls.addWidget(self.recognize_button)
        self.status_label = QLabel("等待识别")
        controls.addWidget(self.status_label, 1)
        right.addLayout(controls)
        self.table = make_table(
            ["识别项", "类型", "状态", "得分", "阈值", "区域", "文本", "耗时(ms)"]
        )
        right.addWidget(self.table, 1)
        self.failure_box = QCheckBox("只看失败/未知")
        self.failure_box.stateChanged.connect(lambda _: self._fill_results())
        right.addWidget(self.failure_box)
        right_widget = QWidget(self)
        right_widget.setLayout(right)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(left_widget)
        splitter.addWidget(self.canvas)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(1, 1)
        layout = QHBoxLayout(self)
        layout.addWidget(splitter)
        self.setLayout(layout)

    def set_source(self, source) -> None:
        self.asset_list.clear()
        if source is None:
            return
        try:
            names = list(source.assets())
        except Exception:
            names = []
        if not names and self.host.vision is not None:
            names = self.host.vision.assets.names()
        for name in names:
            entry = QListWidgetItem(name)
            self.asset_list.addItem(entry)
        self.frame_label.setText(f"数据源: {source.name}")
        self.table.setRowCount(0)
        self._rows = []

    def refresh_frame(self, index: int, frame) -> None:
        self._index = index
        self.canvas.set_frame(frame)
        self.frame_label.setText(
            f"帧 {index + 1}/{self.host.frame_count()}  {frame.frame_id}  "
            f"{frame.width}x{frame.height}"
        )
        self._apply_overlays()
        if self._rows:
            self._rows = []
            self._fill_results()

    def _on_hover(self, point) -> None:
        if point is None:
            self.host.set_status("画布外")
            return
        self.host.set_status(f"画面坐标 ({point[0]}, {point[1]})")

    def recognize(self) -> None:
        if self.host.vision is None or self.canvas.frame is None:
            self.host.set_status("没有可用的识别资源")
            return
        frame = self.canvas.frame
        names = [
            self.asset_list.item(row).text()
            for row in range(self.asset_list.count())
            if self.asset_list.item(row).isSelected()
        ]
        targets = names or None
        self.recognize_button.setEnabled(False)
        self.status_label.setText("识别中…")
        self.host.submit(
            "vision-recognize",
            lambda: recognize_frame(self.host.vision, frame, targets),
            self._on_recognized,
        )

    def _on_recognized(self, rows: list[RecognitionRow]) -> None:
        self.recognize_button.setEnabled(True)
        self._rows = list(rows)
        matched = sum(1 for row in rows if row.status == "matched")
        coordinate = sum(1 for row in rows if row.status == "coordinate_only")
        unknown = sum(1 for row in rows if row.status == "unknown")
        self.status_label.setText(
            f"共 {len(rows)} 项：matched {matched}，coordinate_only {coordinate}，"
            f"unknown {unknown}，miss {len(rows) - matched - coordinate - unknown}"
        )
        self._fill_results()
        self._apply_overlays()

    def _fill_results(self) -> None:
        only_failures = self.failure_box.isChecked()
        rows = []
        for row in self._rows:
            if only_failures and row.status in ("matched", "coordinate_only"):
                continue
            rows.append(
                [
                    row.name,
                    row.kind,
                    row.status,
                    format_score(row.score),
                    format_score(row.threshold),
                    format_rect(row.rect),
                    row.text or "-",
                    f"{row.duration_ms:.1f}",
                ]
            )
        fill_table(self.table, rows, status_column=2)

    def _apply_overlays(self) -> None:
        overlays: list[Overlay] = []
        for row in self._rows:
            if row.rect is None:
                continue
            label = f"{row.name} {row.status}"
            if row.score is not None:
                label += f" {row.score:.2f}"
            overlays.append(
                Overlay(
                    rect=row.rect,
                    label=label,
                    color=STATUS_COLORS.get(row.status, (200, 200, 200)),
                )
            )
        self.canvas.set_overlays(overlays)
        rois: list[Overlay] = []
        if self.show_roi.isChecked() and self.host.vision is not None:
            limit = self.asset_list.count() or 0
            for row in range(limit):
                item = self.asset_list.item(row)
                if item is None or not item.isSelected():
                    continue
                try:
                    spec = self.host.vision.assets.recognition(item.text())
                except Exception:
                    continue
                if spec.roi is not None:
                    rois.append(
                        Overlay(
                            rect=spec.roi,
                            label=f"ROI {item.text()}",
                            color=(90, 160, 230),
                            dashed=True,
                            width=1,
                        )
                    )
        self.canvas.set_rois(rois)
