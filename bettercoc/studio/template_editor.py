from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .canvas import ImageCanvas, numpy_to_qimage
from .recognition import evaluate_draft, export_draft
from .widgets import fill_table, format_rect, make_table

TRIAL_ROWS = ("true_positive", "false_negative", "false_positive", "true_negative", "unlabeled_hit")


class TemplateEditor(QWidget):
    def __init__(self, host, parent=None) -> None:
        super().__init__(parent)
        self.host = host
        self.canvas = ImageCanvas(self)
        self.canvas.selectionChanged.connect(self._on_selection)

        self.selection_label = QLabel("在画布上拖拽框选模板区域")
        self.preview = QLabel("无选区")
        self.preview.setFixedSize(240, 160)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:#1b1e24; color:#8a90a0; border:1px solid #333;")
        self.name_edit = QLineEdit("draft")
        self.roi_edit = QLineEdit("")
        self.roi_edit.setPlaceholderText("可选：x,y,w,h，限制匹配区域")
        self.threshold_spin = QDoubleSpinBox(self)
        self.threshold_spin.setRange(0.3, 1.0)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setValue(0.86)
        self.grayscale_box = QCheckBox("灰度匹配")
        self.grayscale_box.setChecked(True)
        self.trial_button = QPushButton("在固定测试集试验阈值")
        self.trial_button.clicked.connect(self.run_trial)
        self.export_button = QPushButton("导出草稿资源")
        self.export_button.clicked.connect(self.export)
        self.export_button.setEnabled(False)
        self.summary = QLabel("未试验")
        self.table = make_table(["阈值", "命中(应有)", "漏检", "误检", "正确排除", "未标注命中"])

        right = QVBoxLayout()
        right.addWidget(QLabel("模板预览"))
        right.addWidget(self.preview)
        form = QFormLayout()
        form.addRow("识别项名称", self.name_edit)
        form.addRow("ROI", self.roi_edit)
        form.addRow("阈值", self.threshold_spin)
        form.addRow("匹配方式", self.grayscale_box)
        form.addRow("选区", self.selection_label)
        right.addLayout(form)
        right.addWidget(self.trial_button)
        right.addWidget(self.export_button)
        right.addWidget(self.summary)
        right.addWidget(self.table, 1)
        right_widget = QWidget(self)
        right_widget.setLayout(right)
        right_widget.setMinimumWidth(420)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.canvas)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        layout = QHBoxLayout(self)
        layout.addWidget(splitter)
        self.setLayout(layout)

    def set_source(self, source) -> None:
        self.canvas.set_selection(None)
        self.selection_label.setText("在画布上拖拽框选模板区域")
        self.preview.setText("无选区")
        self.preview.setPixmap(QPixmap())

    def refresh_frame(self, index: int, frame) -> None:
        self.canvas.set_frame(frame)
        self.canvas.set_overlays([])
        self.canvas.set_rois([])
        self.export_button.setEnabled(False)
        self.summary.setText("未试验")

    def _on_selection(self, rect) -> None:
        if rect is None:
            self.selection_label.setText("在画布上拖拽框选模板区域")
            self.preview.setText("无选区")
            self.preview.setPixmap(QPixmap())
            self.export_button.setEnabled(False)
            return
        self.selection_label.setText(
            f"{format_rect(rect)}  ({rect.width}x{rect.height})"
        )
        image = self.canvas.selected_image()
        if image is not None:
            pixmap = QPixmap.fromImage(numpy_to_qimage(image))
            self.preview.setPixmap(
                pixmap.scaled(
                    232,
                    152,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.export_button.setEnabled(True)

    def run_trial(self) -> None:
        image = self.canvas.selected_image()
        manifest = self.host.fixture_manifest
        if image is None:
            QMessageBox.information(self, "模板试验", "先在画布上框选一个区域")
            return
        if manifest is None:
            QMessageBox.warning(self, "模板试验", "没有可用的固定测试集")
            return
        base = self.threshold_spin.value()
        thresholds = sorted(
            {
                max(0.3, round(base - 0.04, 3)),
                max(0.3, round(base - 0.02, 3)),
                round(base, 3),
                round(min(1.0, base + 0.02), 3),
            }
        )
        name = self.name_edit.text().strip() or "draft"
        grayscale = self.grayscale_box.isChecked()
        try:
            roi = self._roi()
        except ValueError as exc:
            QMessageBox.warning(self, "模板试验", f"ROI 格式错误: {exc}")
            return
        self.trial_button.setEnabled(False)
        self.summary.setText("试验中…")
        self.host.submit(
            "template-trial",
            lambda: evaluate_draft(
                manifest,
                image,
                thresholds,
                grayscale=grayscale,
                name=name,
                roi=roi,
            ),
            self._on_trial,
        )

    def _roi(self):
        from ..geometry import Rect

        text = self.roi_edit.text().strip()
        if not text:
            return None
        return Rect.from_value(text)

    def _on_trial(self, result) -> None:
        self.trial_button.setEnabled(True)
        rows = []
        for item in result["thresholds"]:
            counts = item["counts"]
            rows.append(
                [
                    f"{item['threshold']:.2f}",
                    counts.get("true_positive", 0),
                    counts.get("false_negative", 0),
                    counts.get("false_positive", 0),
                    counts.get("true_negative", 0),
                    counts.get("unlabeled_hit", 0),
                ]
            )
        fill_table(self.table, rows)
        best = min(
            result["thresholds"],
            key=lambda item: (
                item["counts"].get("false_positive", 0)
                + item["counts"].get("false_negative", 0),
                abs(item["threshold"] - self.threshold_spin.value()),
            ),
        )
        self._trial_result = result
        self._best_threshold = best["threshold"]
        self.summary.setText(
            f"{result['frames']} 帧试验完成，当前阈值误检 "
            f"{best['counts'].get('false_positive', 0)} / 漏检 "
            f"{best['counts'].get('false_negative', 0)}，建议阈值 {best['threshold']:.2f}"
        )

    def export(self) -> None:
        image = self.canvas.selected_image()
        if image is None:
            return
        name = self.name_edit.text().strip() or "draft"
        safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in name)
        target = Path(self.host.workspace) / "drafts" / (safe or "draft")
        threshold = getattr(self, "_best_threshold", self.threshold_spin.value())
        try:
            roi = self._roi()
        except ValueError:
            roi = None
        result = export_draft(
            target,
            name,
            image,
            threshold,
            grayscale=self.grayscale_box.isChecked(),
            source_note=f"Vision Studio, 帧 {self.canvas.frame.frame_id if self.canvas.frame else '-'}",
            roi=roi,
        )
        QMessageBox.information(
            self,
            "草稿已导出",
            "已写入草稿目录，未修改正式资源：\n"
            f"模板: {result['template']}\n片段: {result['fragment']}\n说明: {result['readme']}",
        )
