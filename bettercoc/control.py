from __future__ import annotations

from typing import Protocol

from .adb import AdbDevice
from .errors import TaskError


class Controller(Protocol):
    def tap(self, x: int, y: int) -> None: ...

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None: ...

    def key(self, code: int | str) -> None: ...

    def scroll(self, x: int, y: int, vertical: int) -> None: ...

    def pinch(
        self,
        center_x: int = 540,
        center_y: int = 960,
        start_radius: int = 260,
        end_radius: int = 40,
        steps: int = 12,
    ) -> None: ...

    def force_stop(self, package: str) -> None: ...

    def start_app(self, package: str) -> None: ...


class AdbController:
    def __init__(self, device: AdbDevice) -> None:
        self.device = device

    def tap(self, x: int, y: int) -> None:
        self.device.tap(x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.device.swipe(x1, y1, x2, y2, duration_ms)

    def key(self, code: int | str) -> None:
        self.device.key(code)

    def scroll(self, x: int, y: int, vertical: int) -> None:
        self.device.scroll(x, y, vertical)

    def pinch(
        self,
        center_x: int = 540,
        center_y: int = 960,
        start_radius: int = 260,
        end_radius: int = 40,
        steps: int = 12,
    ) -> None:
        self.device.pinch(center_x, center_y, start_radius, end_radius, steps)

    def force_stop(self, package: str) -> None:
        self.device.force_stop(package)

    def start_app(self, package: str) -> None:
        self.device.start_app(package)


class NullController:
    def tap(self, x: int, y: int) -> None:
        return None

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        return None

    def key(self, code: int | str) -> None:
        return None

    def scroll(self, x: int, y: int, vertical: int) -> None:
        return None

    def pinch(
        self,
        center_x: int = 540,
        center_y: int = 960,
        start_radius: int = 260,
        end_radius: int = 40,
        steps: int = 12,
    ) -> None:
        return None

    def force_stop(self, package: str) -> None:
        raise TaskError("空控制后端不支持重启游戏")

    def start_app(self, package: str) -> None:
        raise TaskError("空控制后端不支持重启游戏")
