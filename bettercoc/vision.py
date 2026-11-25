from __future__ import annotations

import numpy as np

from .color import find_color
from .digits import DigitReader
from .errors import MissingAssetError
from .geometry import Rect
from .image import Screen
from .ocr import NullOcr, OcrBackend, filter_text
from .result import Match, RecognitionStatus
from .spec import Kind, PointCheck, Recognition
from .template import find_template


class Vision:
    def __init__(
        self,
        assets,
        ocr: OcrBackend | None = None,
        digits: DigitReader | None = None,
    ) -> None:
        self.assets = assets
        self.ocr = ocr or NullOcr()
        self.digits = digits

    def resolve(self, target: str | Recognition, roi: Rect | None = None) -> Recognition:
        spec = target if isinstance(target, Recognition) else self.assets.recognition(target)
        if roi is not None:
            spec = spec.with_roi(roi)
        return spec

    def find(
        self,
        screen: Screen,
        target: str | Recognition,
        roi: Rect | None = None,
    ) -> Match | None:
        matches = self.find_all(screen, target, roi=roi, limit=1)
        return matches[0] if matches else None

    def find_all(
        self,
        screen: Screen,
        target: str | Recognition,
        roi: Rect | None = None,
        limit: int = 30,
    ) -> list[Match]:
        spec = self.resolve(target, roi)
        matches = self._find_all(screen, spec, limit)
        frame_id = getattr(screen, "frame_id", None)
        for match in matches:
            if frame_id is not None:
                match.frame_id = frame_id
            if match.threshold is None:
                match.threshold = spec.threshold
        return matches

    def _find_all(
        self, screen: Screen, spec: Recognition, limit: int
    ) -> list[Match]:
        if spec.kind is Kind.POINT:
            return self._find_point(screen, spec, limit)
        if spec.kind is Kind.TEMPLATE:
            template = self.assets.template(spec)
            return find_template(screen, template, spec, limit=limit)
        if spec.kind is Kind.COLOR:
            return find_color(screen, spec, limit=limit)
        if spec.kind is Kind.DIGITS:
            if self.digits is None:
                raise MissingAssetError("数字识别器未配置")
            value, text, score = self.digits.read(screen, spec.roi)
            if value is None:
                return []
            rect = spec.roi or Rect(0, 0, screen.width, screen.height)
            return [Match(rect=rect, score=score, text=text, name=spec.name)]
        raw = self.ocr.read(screen, spec)
        filtered = filter_text(raw, spec)
        filtered.sort(key=lambda item: item.score, reverse=True)
        return filtered[:limit]

    def _find_point(
        self, screen: Screen, spec: Recognition, limit: int
    ) -> list[Match]:
        point = spec.point
        if point is None:
            raise MissingAssetError(f"识别项 {spec.name} 没有固定坐标")
        if spec.check is not None and not self.point_check(screen, spec.check):
            return []
        status = (
            RecognitionStatus.MATCHED
            if spec.check is not None
            else RecognitionStatus.COORDINATE_ONLY
        )
        return [
            Match(
                rect=Rect(point[0], point[1], 1, 1),
                score=1.0,
                name=spec.name,
                status=status,
            )
        ]

    @staticmethod
    def point_check(screen: Screen, check: PointCheck) -> bool:
        roi = check.roi.clamp(screen.width, screen.height)
        if roi.is_empty():
            return False
        patch = screen.crop(roi)
        mean = patch.reshape(-1, 3).astype(np.float32).mean(axis=0)
        targets = np.array(check.colors, dtype=np.float32)
        distances = np.abs(targets - mean).max(axis=1)
        return bool((distances <= check.tolerance).any())

    def describe(self, name: str) -> str:
        spec = self.assets.recognition(name)
        if spec.kind is Kind.POINT:
            detail = f"point {spec.point}"
            if spec.check is not None:
                detail += (
                    f" check roi={spec.check.roi} colors={spec.check.colors}"
                    f" tolerance={spec.check.tolerance}"
                )
            return detail
        if spec.kind is Kind.TEMPLATE:
            return f"template {spec.file} roi={spec.roi} threshold={spec.threshold}"
        if spec.kind is Kind.COLOR:
            return f"color {spec.space} roi={spec.roi} ratio>={spec.min_ratio}"
        if spec.kind is Kind.DIGITS:
            return f"digits roi={spec.roi}"
        return f"ocr roi={spec.roi} any={spec.text_any} all={spec.text_all} regex={spec.regex}"
