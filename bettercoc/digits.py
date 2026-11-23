from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .geometry import Rect
from .image import Screen

GLYPH_WIDTH = 24
GLYPH_HEIGHT = 32


def normalize_glyph(glyph: np.ndarray) -> np.ndarray:
    binary = (glyph > 0).astype(np.uint8) * 255
    ys, xs = np.where(binary > 0)
    if len(xs) == 0:
        return np.zeros((GLYPH_HEIGHT, GLYPH_WIDTH), dtype=np.uint8)
    crop = binary[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    height, width = crop.shape
    scale = min((GLYPH_WIDTH - 4) / width, (GLYPH_HEIGHT - 4) / height)
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    resized = cv2.resize(crop, new_size, interpolation=cv2.INTER_NEAREST)
    canvas = np.zeros((GLYPH_HEIGHT, GLYPH_WIDTH), dtype=np.uint8)
    top = (GLYPH_HEIGHT - new_size[1]) // 2
    left = (GLYPH_WIDTH - new_size[0]) // 2
    canvas[top : top + new_size[1], left : left + new_size[0]] = resized
    return canvas


def white_mask(region: np.ndarray, threshold: int = 170) -> np.ndarray:
    blue, green, red = cv2.split(region)
    mask = (blue > threshold) & (green > threshold) & (red > threshold)
    return mask.astype(np.uint8) * 255


def glyph_boxes(
    mask: np.ndarray,
    max_height: int = 33,
    max_width: int = 30,
) -> list[tuple[int, int, int, int]]:
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    boxes = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if not 4 <= width <= max_width:
            continue
        if not 10 <= height <= max_height:
            continue
        if area < 40:
            continue
        if width > height * 1.2:
            continue
        boxes.append((int(x), int(y), int(width), int(height)))
    boxes.sort(key=lambda item: item[0])
    if len(boxes) < 2:
        return boxes
    heights = sorted(item[3] for item in boxes)
    tops = sorted(item[1] for item in boxes)
    median_height = heights[len(heights) // 2]
    median_top = tops[len(tops) // 2]
    return [
        box
        for box in boxes
        if abs(box[1] - median_top) <= 6 and abs(box[3] - median_height) <= 6
    ]


class DigitReader:
    def __init__(self, template_dir: str | Path) -> None:
        self.template_dir = Path(template_dir)
        self.templates: dict[str, list[np.ndarray]] = {}
        self._load()

    def _load(self) -> None:
        if not self.template_dir.exists():
            return
        for path in sorted(self.template_dir.glob("*.png")):
            label = path.stem.split("-")[0]
            if label not in tuple("0123456789,"):
                continue
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            if image.shape != (GLYPH_HEIGHT, GLYPH_WIDTH):
                image = cv2.resize(
                    image, (GLYPH_WIDTH, GLYPH_HEIGHT), interpolation=cv2.INTER_NEAREST
                )
            binary = (image > 127).astype(np.uint8) * 255
            self.templates.setdefault(label, []).append(binary)

    def available(self) -> bool:
        return all(str(digit) in self.templates for digit in range(10))

    def _classify(self, glyph: np.ndarray) -> tuple[str | None, float]:
        normalized = normalize_glyph(glyph)
        best_label = None
        best_score = -1.0
        for label, templates in self.templates.items():
            for template in templates:
                score = float(np.mean(normalized == template))
                if score > best_score:
                    best_score = score
                    best_label = label
        if best_score < 0.45:
            return None, best_score
        return best_label, best_score

    def read(
        self,
        screen: Screen,
        roi: Rect | None,
        max_height: int = 33,
        max_width: int = 30,
        white_threshold: int = 170,
    ) -> tuple[int | None, str, float]:
        region = screen.image
        if roi is not None:
            clamped = roi.clamp(screen.width, screen.height)
            region = screen.crop(clamped)
        mask = white_mask(region, threshold=white_threshold)
        digits: list[str] = []
        scores: list[float] = []
        for x, y, width, height in glyph_boxes(
            mask, max_height=max_height, max_width=max_width
        ):
            glyph = mask[y : y + height, x : x + width]
            label, score = self._classify(glyph)
            if label is None or label == ",":
                continue
            digits.append(label)
            scores.append(score)
        text = "".join(digits)
        value = int(text) if text else None
        confidence = sum(scores) / len(scores) if scores else 0.0
        return value, text, confidence
