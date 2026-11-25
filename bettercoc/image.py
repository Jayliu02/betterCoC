from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .geometry import Rect, Viewport


@dataclass
class Screen:
    image: np.ndarray
    viewport: Viewport
    source: str = "unknown"
    captured_at: float = field(default_factory=time.monotonic)
    frame_id: str | None = None
    sequence: int = 0

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    def crop(self, rect: Rect) -> np.ndarray:
        clamped = rect.clamp(self.width, self.height)
        return self.image[clamped.y : clamped.bottom, clamped.x : clamped.right]

    def gray(self) -> np.ndarray:
        return cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)


def normalize_frame(frame: np.ndarray, canonical: tuple[int, int]) -> Screen:
    if frame is None or frame.size == 0:
        raise ValueError("截图内容为空")
    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    elif frame.shape[2] == 4:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    device_height, device_width = frame.shape[:2]
    canonical_width, canonical_height = canonical
    if (device_width, device_height) == (canonical_width, canonical_height):
        image = np.ascontiguousarray(frame)
    else:
        shrinking = canonical_width < device_width or canonical_height < device_height
        interpolation = cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR
        image = cv2.resize(
            frame, (canonical_width, canonical_height), interpolation=interpolation
        )
    viewport = Viewport(
        device_width=device_width,
        device_height=device_height,
        canonical_width=canonical_width,
        canonical_height=canonical_height,
    )
    return Screen(image=image, viewport=viewport)


def load_image(path: str | Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"无法读取图片: {path}")
    return image


def save_image(path: str | Path, image: np.ndarray) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = target.suffix or ".png"
    ok, buffer = cv2.imencode(suffix, image)
    if not ok:
        raise ValueError(f"无法编码图片: {path}")
    buffer.tofile(str(target))


def encode_png(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("无法编码 PNG")
    return buffer.tobytes()
