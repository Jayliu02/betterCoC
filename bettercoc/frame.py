from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .errors import CaptureError
from .geometry import Rect, Viewport
from .image import Screen, normalize_frame

DEFAULT_STALE_AFTER = 2.0


def _readonly(image: np.ndarray) -> np.ndarray:
    view = image.view()
    view.flags.writeable = False
    return view


@dataclass
class Frame:
    frame_id: str
    source_id: str
    image: np.ndarray
    viewport: Viewport
    raw_size: tuple[int, int]
    captured_at: float
    captured_wall: float
    sequence: int = 0
    stale_after: float = DEFAULT_STALE_AFTER

    def __post_init__(self) -> None:
        if self.image is None or getattr(self.image, "size", 0) == 0:
            raise CaptureError("帧图像为空")
        if not self.image.flags.writeable:
            return
        self.image = _readonly(self.image)

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    @property
    def canonical_size(self) -> tuple[int, int]:
        return self.width, self.height

    def age(self, now: float | None = None) -> float:
        current = time.monotonic() if now is None else now
        return max(0.0, current - self.captured_at)

    def is_stale(self, max_age: float | None = None, now: float | None = None) -> bool:
        limit = self.stale_after if max_age is None else max_age
        return self.age(now=now) > limit

    def copy_image(self) -> np.ndarray:
        return self.image.copy()

    def crop(self, rect: Rect) -> np.ndarray:
        clamped = rect.clamp(self.width, self.height)
        return self.image[clamped.y : clamped.bottom, clamped.x : clamped.right]

    def to_screen(self) -> Screen:
        return Screen(
            image=self.image,
            viewport=self.viewport,
            source=self.source_id,
            captured_at=self.captured_at,
            frame_id=self.frame_id,
            sequence=self.sequence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "source_id": self.source_id,
            "sequence": self.sequence,
            "captured_at": round(self.captured_at, 6),
            "captured_wall": round(self.captured_wall, 3),
            "raw_size": [int(self.raw_size[0]), int(self.raw_size[1])],
            "canonical_size": [self.width, self.height],
            "viewport": {
                "device_width": self.viewport.device_width,
                "device_height": self.viewport.device_height,
                "canonical_width": self.viewport.canonical_width,
                "canonical_height": self.viewport.canonical_height,
            },
        }


def frame_from_screen(
    screen: Screen,
    source_id: str | None = None,
    sequence: int = 0,
    stale_after: float = DEFAULT_STALE_AFTER,
    clock=time.time,
) -> Frame:
    frame_id = screen.frame_id or f"{source_id or screen.source}-{sequence:06d}"
    return Frame(
        frame_id=frame_id,
        source_id=source_id or screen.source,
        image=screen.image,
        viewport=screen.viewport,
        raw_size=(screen.viewport.device_width, screen.viewport.device_height),
        captured_at=screen.captured_at,
        captured_wall=clock(),
        sequence=sequence,
        stale_after=stale_after,
    )


class FrameProvider:
    def __init__(
        self,
        capture,
        canonical: tuple[int, int] = (1920, 1080),
        source_id: str | None = None,
        clock=time.monotonic,
        wall_clock=time.time,
        stale_after: float = DEFAULT_STALE_AFTER,
    ) -> None:
        self.source = capture
        self.canonical = (int(canonical[0]), int(canonical[1]))
        self.source_id = source_id or str(
            getattr(capture, "description", type(capture).__name__)
        )
        self.clock = clock
        self.wall_clock = wall_clock
        self.stale_after = float(stale_after)
        self.sequence = 0
        self.last_frame: Frame | None = None

    def capture(self) -> Frame:
        raw = self.source.grab()
        if raw is None or getattr(raw, "size", 0) == 0:
            raise CaptureError("截图内容为空")
        raw_height, raw_width = int(raw.shape[0]), int(raw.shape[1])
        screen = normalize_frame(raw, self.canonical)
        self.sequence += 1
        frame = Frame(
            frame_id=f"{self.source_id}-{self.sequence:06d}",
            source_id=self.source_id,
            image=screen.image,
            viewport=screen.viewport,
            raw_size=(raw_width, raw_height),
            captured_at=float(self.clock()),
            captured_wall=float(self.wall_clock()),
            sequence=self.sequence,
            stale_after=self.stale_after,
        )
        self.last_frame = frame
        return frame

    def refresh(self) -> Frame:
        return self.capture()

    def peek(self) -> Frame | None:
        return self.last_frame
