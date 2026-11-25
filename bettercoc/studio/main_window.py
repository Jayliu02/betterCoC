from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..baseline import load_fixture_manifest
from ..config import Config
from ..errors import BetterCoCError
from ..log import get_logger
from ..studio.log_panel import LogPanel
from ..studio.replay_panel import ReplayPanel
from ..studio.settings_panel import SettingsPanel
from ..studio.source import FixtureSource, LiveSource, StudioSource, open_source
from ..studio.template_editor import TemplateEditor
from ..studio.vision_panel import VisionPanel
from ..studio.widgets import format_rect
from ..studio.worker import BackgroundRunner

DEFAULT_FIXTURES = Path("tests/fixtures/baseline")
DEFAULT_WORKSPACE = Path("runtime/studio")


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: Config | None = None,
        source_path: str | Path | None = None,
        workspace: str | Path = DEFAULT_WORKSPACE,
        fixtures: str | Path = DEFAULT_FIXTURES,
    ) -> None:
        super().__init__()
        self.setWindowTitle(f"betterCoC Vision Studio {__version__}")
        self.resize(1600, 940)
        self.config = config
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger()
        self.vision = self._build_vision()
        self.fixture_manifest = self._load_fixtures(fixtures)
        self.runner = BackgroundRunner(max_pending=4, parent=self)
        self.runner.result.connect(self._on_result)
        self.runner.error.connect(self._on_error)
        self.runner.rejected.connect(self._on_rejected)
        self.runner.busyChanged.connect(self._on_busy)
        self._callbacks: dict[str, object] = {}
        self.source: StudioSource | None = None
        self._index = 0
        self._components = None

        self.vision_panel = VisionPanel(self)
        self.template_panel = TemplateEditor(self)
        self.replay_panel = ReplayPanel(self)
        self.log_panel = LogPanel(self)
        self.settings_panel = SettingsPanel(self)
        self.panels = [
            self.vision_panel,
            self.template_panel,
            self.replay_panel,
            self.log_panel,
            self.settings_panel,
        ]

        self.nav = QListWidget(self)
        self.nav.setFixedWidth(150)
        for title in ("Vision", "Template", "Replay", "Logs", "Settings"):
            self.nav.addItem(title)
        self.stack = QStackedWidget(self)
        for panel in self.panels:
            self.stack.addWidget(panel)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        toolbar = QHBoxLayout()
        self.source_button = QPushButton("选择数据源…")
        self.source_button.clicked.connect(self.pick_source)
        self.live_button = QPushButton("连接设备只读预览")
        self.live_button.clicked.connect(self.connect_live)
        self.source_label = QLabel("未加载数据源")
        toolbar.addWidget(self.source_button)
        toolbar.addWidget(self.live_button)
        toolbar.addWidget(self.source_label, 1)

        body = QWidget(self)
        body_layout = QHBoxLayout(body)
        splitter = QSplitter(Qt.Orientation.Horizontal, body)
        splitter.addWidget(self.nav)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        body_layout.addWidget(splitter)
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addLayout(toolbar)
        layout.addWidget(body, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")
        self.queue_label = QLabel("后台: 空闲")
        self.statusBar().addPermanentWidget(self.queue_label)

        if self.vision is None:
            self.set_status("资源清单不可用，仅能浏览图像与事件")
        if source_path is not None:
            self.load_source_path(source_path)
        elif self.fixture_manifest is not None:
            self.load_source_object(FixtureSource(DEFAULT_FIXTURES))

    def _build_vision(self):
        if self.config is None:
            return None
        try:
            from ..app import build_vision

            return build_vision(self.config)
        except Exception as exc:
            self.set_status(f"加载识别资源失败: {exc}")
            return None

    def _load_fixtures(self, fixtures):
        try:
            return load_fixture_manifest(fixtures)
        except BetterCoCError:
            return None

    def load_source_path(self, path: str | Path) -> None:
        try:
            source = open_source(path)
        except BetterCoCError as exc:
            self.set_status(f"加载数据源失败: {exc}")
            return
        self.load_source_object(source)

    def load_source_object(self, source: StudioSource) -> None:
        if self.source is not None and self.source is not source:
            self.source.close()
        self.source = source
        self._index = 0
        self.source_label.setText(f"{source.name}: {source.description}")
        if isinstance(source, FixtureSource):
            self.fixture_manifest = source.manifest
        for panel in self.panels:
            setter = getattr(panel, "set_source", None)
            if setter is not None:
                setter(source)
        self.settings_panel.refresh()
        self.refresh_frame(0)
    def pick_source(self) -> None:
        start = str(self.source.description) if self.source is not None else ""
        path = QFileDialog.getExistingDirectory(self, "选择固定测试集或录制会话", start)
        if path:
            self.load_source_path(path)

    def connect_live(self) -> None:
        if self.config is None:
            self.set_status("没有配置文件，无法连接设备")
            return
        from ..app import build_context

        try:
            components = build_context(self.config, self.logger)
        except Exception as exc:
            self.set_status(f"设备不可用: {exc}")
            return
        self._components = components
        canonical = tuple(self.config.get("vision.canonical_size", [1920, 1080]))
        source = LiveSource(components.capture, (int(canonical[0]), int(canonical[1])))
        self.load_source_object(source)
        self.set_status("已连接设备只读预览；不会发送任何输入")

    def frame_count(self) -> int:
        if self.source is None:
            return 0
        return self.source.frame_count()

    def step_frame(self, delta: int) -> None:
        total = self.frame_count()
        if total <= 0:
            return
        self.refresh_frame(max(0, min(self._index + delta, total - 1)))

    def refresh_frame(self, index: int) -> None:
        if self.source is None:
            return
        if isinstance(self.source, LiveSource):
            self.submit("live-capture", self.source.refresh, self._apply_live_frame)
            return
        total = self.frame_count()
        if total <= 0:
            return
        self._index = max(0, min(index, total - 1))
        try:
            item = self.source.frame(self._index)
        except Exception as exc:
            self.set_status(f"读取帧失败: {exc}")
            return
        self._apply_frame(item)

    def _apply_frame(self, item) -> None:
        total = self.frame_count()
        for panel in self.panels:
            updater = getattr(panel, "refresh_frame", None)
            if updater is not None:
                updater(self._index, item.frame)
        age = item.frame.age()
        self.set_status(
            f"帧 {self._index + 1}/{total}  帧龄 {age:.2f}s"
        )

    def _apply_live_frame(self, item) -> None:
        self._index = 0
        self._apply_frame(item)
        self.set_status(f"实时帧 {item.frame.frame_id}  帧龄 {item.frame.age():.2f}s")

    def _selection_rect(self):
        return self.template_panel.canvas.selection

    def submit(self, job_id: str, func, callback) -> None:
        self._callbacks[job_id] = callback
        if not self.runner.submit(job_id, func):
            self._callbacks.pop(job_id, None)

    def _on_result(self, job_id: str, result) -> None:
        callback = self._callbacks.pop(job_id, None)
        if callable(callback):
            callback(result)
        self.set_status(f"{job_id} 完成")

    def _on_error(self, job_id: str, exc) -> None:
        self._callbacks.pop(job_id, None)
        self.set_status(f"{job_id} 失败: {exc}")

    def _on_rejected(self, job_id: str, reason: str) -> None:
        self._callbacks.pop(job_id, None)
        self.set_status(f"{job_id} 被拒绝: {reason}")

    def _on_busy(self, busy: bool) -> None:
        self.queue_label.setText(f"后台: {'忙碌' if busy else '空闲'} ({self.runner.pending})")

    def set_status(self, text: str) -> None:
        self.statusBar().showMessage(str(text))

    def render_screenshot(self, path: str | Path, width: int = 1600, height: int = 940) -> Path:
        from ..studio.recognition import recognize_frame

        self.resize(width, height)
        self.show()
        self.nav.setCurrentRow(0)
        QApplication.processEvents()
        if self.source is not None and self.vision is not None and self.frame_count() > 0:
            self.refresh_frame(self._index)
            item = self.source.frame(self._index)
            rows = recognize_frame(self.vision, item.frame)
            self.vision_panel._on_recognized(rows)
        QApplication.processEvents()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.grab().save(str(target))
        return target

    def closeEvent(self, event) -> None:
        try:
            self.runner.shutdown()
        finally:
            if self.source is not None:
                self.source.close()
            if self._components is not None:
                try:
                    self._components.context.close()
                except Exception:
                    pass
        super().closeEvent(event)
