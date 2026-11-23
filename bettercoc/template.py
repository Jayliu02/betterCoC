from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .geometry import Rect
from .image import Screen
from .result import Match
from .spec import Recognition


@dataclass
class Template:
    name: str
    image: np.ndarray
    mask: np.ndarray | None = None
    _cache: dict[tuple[bool, float], tuple[np.ndarray, np.ndarray | None]] = field(
        default_factory=dict, repr=False
    )

    def prepared(self, grayscale: bool, scale: float) -> tuple[np.ndarray, np.ndarray | None]:
        key = (grayscale, round(scale, 4))
        if key in self._cache:
            return self._cache[key]
        image = self.image
        mask = self.mask
        if scale != 1.0:
            width = max(1, round(image.shape[1] * scale))
            height = max(1, round(image.shape[0] * scale))
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
            if mask is not None:
                mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
        if grayscale:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        self._cache[key] = (image, mask)
        return image, mask


def build_mask(
    image: np.ndarray,
    use_alpha: bool,
    mask_color: tuple[int, int, int] | None,
    tolerance: int,
) -> tuple[np.ndarray, np.ndarray | None]:
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        alpha = image[:, :, 3]
        mask = None
        if use_alpha:
            mask = np.where(alpha > 8, 255, 0).astype(np.uint8)
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR), mask
    if mask_color is not None:
        color = np.array(mask_color, dtype=np.int16)
        diff = np.abs(image.astype(np.int16) - color).max(axis=2)
        mask = np.where(diff > tolerance, 255, 0).astype(np.uint8)
        return image, mask
    return image, None


def _method_id(name: str, has_mask: bool) -> int:
    if has_mask and name == "ccoeff_normed":
        name = "ccorr_normed"
    return {
        "ccoeff_normed": cv2.TM_CCOEFF_NORMED,
        "ccorr_normed": cv2.TM_CCORR_NORMED,
        "sqdiff_normed": cv2.TM_SQDIFF_NORMED,
    }[name]


def _score_map(result: np.ndarray, method: int) -> np.ndarray:
    if method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
        scores = 1.0 - result
    else:
        scores = result
    return np.nan_to_num(scores, nan=-1.0, posinf=-1.0, neginf=-1.0)


def _nms(matches: list[Match], iou_threshold: float, limit: int) -> list[Match]:
    matches.sort(key=lambda item: item.score, reverse=True)
    kept: list[Match] = []
    for match in matches:
        if all(match.rect.iou(other.rect) <= iou_threshold for other in kept):
            kept.append(match)
            if len(kept) >= limit:
                break
    return kept


def _region(image: Screen, roi: Rect | None) -> tuple[np.ndarray, Rect]:
    if roi is None:
        full = Rect(0, 0, image.width, image.height)
        return image.image, full
    clamped = roi.clamp(image.width, image.height)
    return image.crop(clamped), clamped


def find_template(
    screen: Screen,
    template: Template,
    spec: Recognition,
    limit: int = 1,
) -> list[Match]:
    region, roi = _region(screen, spec.roi)
    region_height, region_width = region.shape[:2]
    if region_width == 0 or region_height == 0:
        return []
    match_region = (
        cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) if spec.grayscale else region
    )

    def collect() -> list[Match]:
        candidates: list[Match] = []
        for scale in spec.scales:
            image, mask = template.prepared(spec.grayscale, scale)
            template_height, template_width = image.shape[:2]
            if template_width > region_width or template_height > region_height:
                continue
            method = _method_id(spec.method, mask is not None)
            result = cv2.matchTemplate(match_region, image, method, mask=mask)
            scores = _score_map(result, method)
            if limit == 1:
                _, best_score, _, best_location = cv2.minMaxLoc(scores)
                if best_score >= spec.threshold:
                    candidates.append(
                        Match(
                            rect=Rect(
                                roi.x + best_location[0],
                                roi.y + best_location[1],
                                template_width,
                                template_height,
                            ),
                            score=float(best_score),
                            name=spec.name,
                        )
                    )
                continue
            ys, xs = np.where(scores >= spec.threshold)
            if len(xs) > 5000:
                flat = scores[ys, xs]
                order = np.argpartition(flat, -5000)[-5000:]
                xs, ys = xs[order], ys[order]
            for x, y in zip(xs.tolist(), ys.tolist()):
                candidates.append(
                    Match(
                        rect=Rect(
                            roi.x + x,
                            roi.y + y,
                            template_width,
                            template_height,
                        ),
                        score=float(scores[y, x]),
                        name=spec.name,
                    )
                )
        return candidates

    found = collect()
    if not found:
        return []
    if limit == 1:
        found.sort(key=lambda item: item.score, reverse=True)
        return found[:1]
    return _nms(found, 0.3, limit)
