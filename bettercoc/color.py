from __future__ import annotations

import cv2
import numpy as np

from .geometry import Rect
from .image import Screen
from .result import Match
from .spec import Recognition


def _region(screen: Screen, roi: Rect | None) -> tuple[np.ndarray, Rect]:
    if roi is None:
        full = Rect(0, 0, screen.width, screen.height)
        return screen.image, full
    clamped = roi.clamp(screen.width, screen.height)
    return screen.crop(clamped), clamped


def find_color(screen: Screen, spec: Recognition, limit: int = 1) -> list[Match]:
    region, roi = _region(screen, spec.roi)
    if region.size == 0:
        return []
    if spec.space == "hsv":
        converted = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    else:
        converted = region
    lower = np.array(spec.lower, dtype=np.uint8)
    upper = np.array(spec.upper, dtype=np.uint8)
    mask = cv2.inRange(converted, lower, upper)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    region_area = region.shape[0] * region.shape[1]
    matches: list[Match] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < spec.min_area:
            continue
        ratio = area / region_area if region_area else 0.0
        if ratio < spec.min_ratio:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        matches.append(
            Match(
                rect=Rect(roi.x + x, roi.y + y, width, height),
                score=float(min(1.0, ratio)),
                name=spec.name,
            )
        )
    matches.sort(key=lambda item: item.score, reverse=True)
    return matches[:limit]
