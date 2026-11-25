from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .errors import ConfigError
from .geometry import Rect


class Kind(str, Enum):
    TEMPLATE = "template"
    OCR = "ocr"
    COLOR = "color"
    DIGITS = "digits"
    POINT = "point"


TEMPLATE_METHODS = (
    "ccoeff_normed",
    "ccorr_normed",
    "sqdiff_normed",
)


@dataclass(frozen=True)
class PointCheck:
    roi: Rect
    colors: tuple[tuple[int, int, int], ...]
    tolerance: int = 25

    def __post_init__(self) -> None:
        if self.roi.is_empty():
            raise ConfigError(f"固定位置的颜色校验区域为空: {self.roi}")
        if not self.colors:
            raise ConfigError("固定位置的颜色校验至少需要一个 BGR 颜色")
        for color in self.colors:
            if len(color) != 3:
                raise ConfigError(f"固定位置的颜色校验需要 3 个 BGR 分量: {color}")
        if self.tolerance < 0:
            raise ConfigError(f"颜色校验容差不能为负数: {self.tolerance}")


@dataclass(frozen=True)
class Recognition:
    name: str
    kind: Kind = Kind.TEMPLATE
    roi: Rect | None = None
    threshold: float = 0.86
    grayscale: bool = True
    method: str = "ccoeff_normed"
    scales: tuple[float, ...] = (1.0,)
    file: str | None = None
    point: tuple[int, int] | None = None
    check: PointCheck | None = None
    use_alpha: bool = True
    mask_color: tuple[int, int, int] | None = None
    mask_tolerance: int = 12
    text_any: tuple[str, ...] = ()
    text_all: tuple[str, ...] = ()
    regex: str | None = None
    lang: str | None = None
    psm: int = 6
    upscale: float = 2.0
    binarize: bool = False
    invert: bool = False
    space: str = "hsv"
    lower: tuple[int, int, int] = (0, 0, 0)
    upper: tuple[int, int, int] = (255, 255, 255)
    min_area: int = 150
    min_ratio: float = 0.05

    def __post_init__(self) -> None:
        if self.kind is Kind.TEMPLATE:
            if not self.file:
                raise ConfigError(f"识别项 {self.name} 缺少模板文件")
            if self.method not in TEMPLATE_METHODS:
                raise ConfigError(
                    f"识别项 {self.name} 的匹配方法无效: {self.method}"
                )
            if not 0 < self.threshold <= 1:
                raise ConfigError(f"识别项 {self.name} 的阈值需要在 (0,1] 内")
            if not self.scales or any(scale <= 0 for scale in self.scales):
                raise ConfigError(f"识别项 {self.name} 的缩放系数无效")
        if self.kind is Kind.POINT:
            if self.point is None or len(self.point) != 2:
                raise ConfigError(f"识别项 {self.name} 的固定坐标需要 [x, y]")
        if self.kind is Kind.COLOR:
            if self.space not in ("hsv", "bgr"):
                raise ConfigError(f"识别项 {self.name} 的颜色空间无效: {self.space}")
            if len(self.lower) != 3 or len(self.upper) != 3:
                raise ConfigError(f"识别项 {self.name} 的颜色范围需要 3 个分量")
            if not 0 <= self.min_ratio <= 1:
                raise ConfigError(f"识别项 {self.name} 的 min_ratio 需要在 [0,1] 内")

    def with_roi(self, roi: Rect | None) -> "Recognition":
        return replace(self, roi=roi)
