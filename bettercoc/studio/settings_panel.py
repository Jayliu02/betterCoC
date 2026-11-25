from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget

from .. import __version__


class SettingsPanel(QWidget):
    def __init__(self, host, parent=None) -> None:
        super().__init__(parent)
        self.host = host
        self.form = QFormLayout()
        self.form.addRow("betterCoC 版本", QLabel(__version__))
        self.form.addRow("数据源", QLabel("-"))
        self.form.addRow("配置文件", QLabel("-"))
        self.form.addRow("资源清单", QLabel("-"))
        self.form.addRow("数字模板", QLabel("-"))
        self.form.addRow("canonical 尺寸", QLabel("-"))
        self.form.addRow("截图后端", QLabel("-"))
        self.form.addRow("控制后端", QLabel("-"))
        self.form.addRow("工作目录", QLabel(str(host.workspace)))
        note = QLabel(
            "Studio 默认只读：预览与回放不发送触控、按键或应用重启指令。"
            "设备预览使用只读截图，断线时显示不可用。"
        )
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(note)
        layout.addStretch(1)
        self.setLayout(layout)

    def refresh(self) -> None:
        host = self.host
        config = host.config
        source = host.source
        values = [
            source.name if source is not None else "-",
            str(config.path) if config is not None and config.path else "未加载",
            str(host.vision.assets.manifest_path) if host.vision is not None else "-",
            str(config.get("vision.digits", "-")) if config is not None else "-",
            str(config.get("vision.canonical_size", [1920, 1080]))
            if config is not None
            else "-",
            str(config.get("capture.backend", "-")) if config is not None else "-",
            str(config.get("control.backend", "-")) if config is not None else "-",
        ]
        for row, value in enumerate(values):
            item = self.form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            if item is not None and item.widget() is not None:
                item.widget().setText(value)

    def set_source(self, source) -> None:
        self.refresh()

    def refresh_frame(self, index: int, frame) -> None:
        return None
