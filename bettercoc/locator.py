from __future__ import annotations

from .geometry import Rect
from .result import Match


class Locator:
    def __init__(
        self,
        ctx,
        target,
        roi: Rect | None = None,
        timeout: float = 10.0,
        interval: float = 0.3,
    ) -> None:
        self.ctx = ctx
        self.target = target
        self.roi = roi
        self.timeout = timeout
        self.interval = interval

    def find(self) -> Match | None:
        return self.ctx.find(self.target, roi=self.roi)

    def find_all(self, limit: int = 10) -> list[Match]:
        return self.ctx.find_all(self.target, roi=self.roi, limit=limit)

    def exists(self) -> bool:
        return self.find() is not None

    def wait_for(self, timeout: float | None = None) -> Match:
        return self.ctx.wait(
            self.target,
            timeout=self.timeout if timeout is None else timeout,
            interval=self.interval,
            roi=self.roi,
        )

    def try_wait_for(self, timeout: float | None = None) -> Match | None:
        return self.ctx.try_wait(
            self.target,
            timeout=self.timeout if timeout is None else timeout,
            interval=self.interval,
            roi=self.roi,
        )

    def wait_for_disappear(self, timeout: float | None = None) -> None:
        self.ctx.wait_gone(
            self.target,
            timeout=self.timeout if timeout is None else timeout,
            interval=self.interval,
            roi=self.roi,
        )

    def click(self, timeout: float | None = None) -> Match:
        match = self.wait_for(timeout)
        self.ctx.tap_match(match)
        return match

    def click_if_exists(self, timeout: float | None = None) -> Match | None:
        match = self.try_wait_for(timeout)
        if match is not None:
            self.ctx.tap_match(match)
        return match

    def with_roi(self, roi: Rect | None) -> "Locator":
        return Locator(self.ctx, self.target, roi=roi, timeout=self.timeout, interval=self.interval)

    def with_timeout(self, timeout: float) -> "Locator":
        return Locator(
            self.ctx, self.target, roi=self.roi, timeout=timeout, interval=self.interval
        )

    def with_interval(self, interval: float) -> "Locator":
        return Locator(
            self.ctx, self.target, roi=self.roi, timeout=self.timeout, interval=interval
        )
