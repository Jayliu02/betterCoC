from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError(f"矩形宽高不能为负数: {self}")

    @classmethod
    def from_value(cls, value: object) -> "Rect":
        if isinstance(value, Rect):
            return value
        if isinstance(value, dict):
            return cls(
                int(value["x"]),
                int(value["y"]),
                int(value.get("width", value.get("w"))),
                int(value.get("height", value.get("h"))),
            )
        if isinstance(value, str):
            parts = [int(part.strip()) for part in value.split(",")]
            if len(parts) != 4:
                raise ValueError(f"矩形字符串需要 x,y,w,h: {value}")
            return cls(*parts)
        if isinstance(value, Iterable):
            parts = list(value)
            if len(parts) != 4:
                raise ValueError(f"矩形需要 4 个元素: {value}")
            return cls(*(int(part) for part in parts))
        raise TypeError(f"无法解析矩形: {value!r}")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2

    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def clamp(self, width: int, height: int) -> "Rect":
        left = max(0, min(self.x, width))
        top = max(0, min(self.y, height))
        right = max(left, min(self.right, width))
        bottom = max(top, min(self.bottom, height))
        return Rect(left, top, right - left, bottom - top)

    def expand(self, dx: int, dy: int | None = None) -> "Rect":
        if dy is None:
            dy = dx
        return Rect(self.x - dx, self.y - dy, self.width + dx * 2, self.height + dy * 2)

    def intersect(self, other: "Rect") -> "Rect":
        left = max(self.x, other.x)
        top = max(self.y, other.y)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        return Rect(left, top, max(0, right - left), max(0, bottom - top))

    def iou(self, other: "Rect") -> float:
        inter = self.intersect(other).area
        if inter == 0:
            return 0.0
        union = self.area + other.area - inter
        return inter / union if union else 0.0

    def scale(self, fx: float, fy: float | None = None) -> "Rect":
        if fy is None:
            fy = fx
        return Rect(
            round(self.x * fx),
            round(self.y * fy),
            round(self.width * fx),
            round(self.height * fy),
        )

    def to_list(self) -> list[int]:
        return [self.x, self.y, self.width, self.height]

    def __str__(self) -> str:
        return f"({self.x},{self.y},{self.width}x{self.height})"


@dataclass(frozen=True)
class Viewport:
    device_width: int
    device_height: int
    canonical_width: int = 1920
    canonical_height: int = 1080

    @property
    def scale_x(self) -> float:
        return self.device_width / self.canonical_width

    @property
    def scale_y(self) -> float:
        return self.device_height / self.canonical_height

    def to_device(self, x: float, y: float) -> tuple[int, int]:
        device_x = round(x * self.scale_x)
        device_y = round(y * self.scale_y)
        return (
            max(0, min(device_x, self.device_width - 1)),
            max(0, min(device_y, self.device_height - 1)),
        )

    def to_canonical(self, x: float, y: float) -> tuple[int, int]:
        canonical_x = round(x / self.scale_x)
        canonical_y = round(y / self.scale_y)
        return (
            max(0, min(canonical_x, self.canonical_width - 1)),
            max(0, min(canonical_y, self.canonical_height - 1)),
        )
