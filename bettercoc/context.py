from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import Config
from .errors import (
    FrameStaleError,
    MissingAssetError,
    RecognitionTimeout,
    StopRequested,
)
from .frame import Frame, FrameProvider
from .geometry import Rect, Viewport
from .image import Screen, save_image
from .result import Match
from .vision import Vision


@dataclass
class Stats:
    counters: dict[str, int] = field(default_factory=dict)

    def incr(self, key: str, amount: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + amount

    def get(self, key: str, default: int = 0) -> int:
        return self.counters.get(key, default)

    def set(self, key: str, value: int) -> None:
        self.counters[key] = value

    def to_dict(self) -> dict[str, int]:
        return dict(sorted(self.counters.items()))


class Context:
    def __init__(
        self,
        config: Config,
        vision: Vision,
        capture,
        controller,
        logger,
        canonical: tuple[int, int] = (1920, 1080),
        dry_run: bool = False,
        jitter: int = 2,
        tap_delay: tuple[float, float] = (0.12, 0.28),
        clock=time.monotonic,
        sleeper=None,
        rng: random.Random | None = None,
        stale_after: float = 2.0,
    ) -> None:
        self.config = config
        self.vision = vision
        self.capture = capture
        self.controller = controller
        self.logger = logger
        self.canonical = canonical
        self.dry_run = dry_run
        self.jitter = max(0, jitter)
        self.tap_delay = tap_delay
        self.clock = clock
        self._sleeper = sleeper
        self.rng = rng or random.Random()
        self.stats = Stats()
        self.last_screen: Screen | None = None
        self.last_frame: Frame | None = None
        self.viewport: Viewport | None = None
        self.started_at = clock()
        self._stop = threading.Event()
        self._stop_reason = ""
        self._shot_index = 0
        self._optional_warned: set[str] = set()
        self._frames = FrameProvider(
            capture,
            canonical=canonical,
            clock=clock,
            stale_after=stale_after,
        )

    def screen(self) -> Screen:
        return self.capture_frame().to_screen()

    def capture_frame(self) -> Frame:
        frame = self._frames.capture()
        self.last_frame = frame
        self.last_screen = frame.to_screen()
        self.viewport = frame.viewport
        self.stats.incr("captures")
        return frame

    def current_frame(self) -> Frame:
        if self.last_frame is None:
            return self.capture_frame()
        return self.last_frame

    def refresh_frame(self) -> Frame:
        return self.capture_frame()

    def frame_age(self) -> float | None:
        if self.last_frame is None:
            return None
        return self.last_frame.age(now=self.clock())

    def find_in(
        self,
        frame: Frame,
        target: str | object,
        roi: Rect | None = None,
        max_age: float | None = None,
    ) -> Match | None:
        if frame.is_stale(max_age=max_age, now=self.clock()):
            raise FrameStaleError(
                f"帧 {frame.frame_id} 已过期 {frame.age(now=self.clock()):.2f}s，"
                "请先调用 refresh_frame()"
            )
        return self.find(target, screen=frame.to_screen(), roi=roi)

    def find_all_in(
        self,
        frame: Frame,
        target: str | object,
        roi: Rect | None = None,
        limit: int = 30,
        max_age: float | None = None,
    ) -> list[Match]:
        if frame.is_stale(max_age=max_age, now=self.clock()):
            raise FrameStaleError(
                f"帧 {frame.frame_id} 已过期 {frame.age(now=self.clock()):.2f}s，"
                "请先调用 refresh_frame()"
            )
        return self.find_all(target, screen=frame.to_screen(), roi=roi, limit=limit)

    def find(
        self,
        target: str | object,
        screen: Screen | None = None,
        roi: Rect | None = None,
    ) -> Match | None:
        screen = screen or self.screen()
        match = self.vision.find(screen, target, roi=roi)
        if match is not None:
            self.stats.incr("matches")
            self.logger.debug(
                "命中 %s %s score=%.3f text=%s",
                match.name,
                match.rect,
                match.score,
                match.text or "",
            )
        return match

    def locate(
        self,
        target: str | object,
        roi: Rect | None = None,
        timeout: float = 10.0,
        interval: float = 0.3,
    ):
        from .locator import Locator

        return Locator(self, target, roi=roi, timeout=timeout, interval=interval)

    def find_all(
        self,
        target: str | object,
        screen: Screen | None = None,
        roi: Rect | None = None,
        limit: int = 30,
    ) -> list[Match]:
        screen = screen or self.screen()
        matches = self.vision.find_all(screen, target, roi=roi, limit=limit)
        if matches:
            self.stats.incr("matches", len(matches))
        return matches

    def find_optional(
        self,
        name: str,
        screen: Screen | None = None,
        roi: Rect | None = None,
    ) -> Match | None:
        if not self.vision.assets.has(name):
            if name not in self._optional_warned:
                self._optional_warned.add(name)
                self.logger.debug("可选识别项未配置: %s", name)
            return None
        try:
            return self.find(name, screen=screen, roi=roi)
        except MissingAssetError:
            if name not in self._optional_warned:
                self._optional_warned.add(name)
                self.logger.warning("可选识别项缺少模板，已跳过: %s", name)
            return None

    def wait(
        self,
        target: str | object,
        timeout: float = 10.0,
        interval: float = 0.3,
        roi: Rect | None = None,
    ) -> Match:
        self._raise_if_stopped()
        deadline = self.clock() + max(0.0, timeout)
        name = target if isinstance(target, str) else getattr(target, "name", "?")
        while True:
            match = self.find(target, roi=roi)
            if match is not None:
                return match
            remaining = deadline - self.clock()
            if remaining <= 0:
                self.stats.incr("timeouts")
                raise RecognitionTimeout(f"等待识别项 {name} 超时 ({timeout:g}s)")
            self.sleep(min(interval, remaining))

    def try_wait(
        self,
        target: str | object,
        timeout: float = 3.0,
        interval: float = 0.3,
        roi: Rect | None = None,
    ) -> Match | None:
        try:
            return self.wait(target, timeout=timeout, interval=interval, roi=roi)
        except RecognitionTimeout:
            return None

    def wait_gone(
        self,
        target: str | object,
        timeout: float = 10.0,
        interval: float = 0.3,
        roi: Rect | None = None,
    ) -> None:
        deadline = self.clock() + max(0.0, timeout)
        name = target if isinstance(target, str) else getattr(target, "name", "?")
        while True:
            if self.find(target, roi=roi) is None:
                return
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise RecognitionTimeout(f"等待识别项 {name} 消失超时 ({timeout:g}s)")
            self.sleep(min(interval, remaining))

    def click(
        self,
        target: str | object,
        timeout: float = 10.0,
        interval: float = 0.3,
        roi: Rect | None = None,
        offset: tuple[int, int] = (0, 0),
    ) -> Match:
        match = self.wait(target, timeout=timeout, interval=interval, roi=roi)
        self.tap_match(match, offset=offset)
        return match

    def click_if_present(
        self,
        target: str | object,
        timeout: float = 0.8,
        roi: Rect | None = None,
    ) -> Match | None:
        match = self.try_wait(target, timeout=timeout, roi=roi)
        if match is not None:
            self.tap_match(match)
        return match

    def tap_match(self, match: Match, offset: tuple[int, int] = (0, 0)) -> None:
        x, y = match.center
        self.tap(x + offset[0], y + offset[1])

    def tap(self, x: float, y: float) -> None:
        if self.viewport is None:
            self.screen()
        viewport = self.viewport
        assert viewport is not None
        canonical_x = max(0, min(round(x), self.canonical[0] - 1))
        canonical_y = max(0, min(round(y), self.canonical[1] - 1))
        if self.jitter:
            canonical_x += self.rng.randint(-self.jitter, self.jitter)
            canonical_y += self.rng.randint(-self.jitter, self.jitter)
            canonical_x = max(0, min(canonical_x, self.canonical[0] - 1))
            canonical_y = max(0, min(canonical_y, self.canonical[1] - 1))
        device_x, device_y = viewport.to_device(canonical_x, canonical_y)
        self.stats.incr("taps")
        if self.dry_run:
            self.logger.info(
                "[dry-run] tap 画面(%d,%d) -> 设备(%d,%d)",
                canonical_x,
                canonical_y,
                device_x,
                device_y,
            )
        else:
            self.logger.debug(
                "tap 画面(%d,%d) -> 设备(%d,%d)",
                canonical_x,
                canonical_y,
                device_x,
                device_y,
            )
            self.controller.tap(device_x, device_y)
        self._action_delay()

    def swipe(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        duration_ms: int = 300,
    ) -> None:
        if self.viewport is None:
            self.screen()
        viewport = self.viewport
        assert viewport is not None
        start = viewport.to_device(x1, y1)
        end = viewport.to_device(x2, y2)
        self.stats.incr("swipes")
        if not self.dry_run:
            self.controller.swipe(start[0], start[1], end[0], end[1], duration_ms)
        self._action_delay()

    def back(self) -> None:
        self.stats.incr("backs")
        if not self.dry_run:
            self.controller.key(4)
        self._action_delay()

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self._raise_if_stopped()
        if self._sleeper is not None:
            self._sleeper(seconds)
            return
        if self._stop.wait(seconds):
            self._raise_if_stopped()

    def _action_delay(self) -> None:
        low, high = self.tap_delay
        if high <= 0:
            return
        self.sleep(self.rng.uniform(max(0.0, low), max(low, high)))

    def request_stop(self, reason: str = "用户请求停止") -> None:
        if not self._stop.is_set():
            self._stop_reason = reason
        self._stop.set()

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def _raise_if_stopped(self) -> None:
        if self._stop.is_set():
            raise StopRequested(self._stop_reason or "已请求停止")

    @property
    def elapsed(self) -> float:
        return self.clock() - self.started_at

    def runtime_exceeded(self, minutes: float) -> bool:
        return minutes > 0 and self.elapsed >= minutes * 60

    def save_screenshot(
        self,
        label: str,
        screen: Screen | None = None,
        image: np.ndarray | None = None,
    ) -> Path:
        root = Path(
            self.config.resolve_path(
                self.config.get("runtime.screenshot_dir", "runtime/screenshots")
            )
        )
        self._shot_index += 1
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe_label = "".join(char if char.isalnum() or char in "-_" else "_" for char in label)
        target = root / f"{stamp}-{self._shot_index:03d}-{safe_label}.png"
        if image is None:
            image = (screen or self.screen()).image
        save_image(target, image)
        self.logger.info("截图已保存: %s", target)
        return target

    def close(self) -> None:
        self.capture.close()
