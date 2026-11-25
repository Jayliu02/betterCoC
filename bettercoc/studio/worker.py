from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class JobSignals(QObject):
    done = Signal(str, object)
    failed = Signal(str, object)


class Job(QRunnable):
    def __init__(self, job_id: str, func: Callable[[], Any]) -> None:
        super().__init__()
        self.job_id = job_id
        self.func = func
        self.signals = JobSignals()

    def run(self) -> None:
        try:
            result = self.func()
        except Exception as exc:
            self.signals.failed.emit(self.job_id, exc)
            return
        self.signals.done.emit(self.job_id, result)


class BackgroundRunner(QObject):
    result = Signal(str, object)
    error = Signal(str, object)
    rejected = Signal(str, str)
    busyChanged = Signal(bool)

    def __init__(self, max_pending: int = 4, parent=None) -> None:
        super().__init__(parent)
        self.max_pending = max(1, int(max_pending))
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._pending = 0

    @property
    def pending(self) -> int:
        return self._pending

    def submit(self, job_id: str, func: Callable[[], Any]) -> bool:
        if self._pending >= self.max_pending:
            self.rejected.emit(job_id, f"后台队列已满（{self.max_pending}），已拒绝")
            return False
        self._pending += 1
        self.busyChanged.emit(True)
        job = Job(job_id, func)
        job.signals.done.connect(self._on_done)
        job.signals.failed.connect(self._on_failed)
        self.pool.start(job)
        return True

    def _on_done(self, job_id: str, result: Any) -> None:
        self._pending = max(0, self._pending - 1)
        self.busyChanged.emit(self._pending > 0)
        self.result.emit(job_id, result)

    def _on_failed(self, job_id: str, exc: BaseException) -> None:
        self._pending = max(0, self._pending - 1)
        self.busyChanged.emit(self._pending > 0)
        self.error.emit(job_id, exc)

    def shutdown(self, timeout_ms: int = 5000) -> None:
        self.pool.clear()
        self.pool.waitForDone(timeout_ms)
        self._pending = 0
