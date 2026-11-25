from __future__ import annotations

import cv2
import numpy as np

from .result import Match


def annotate_matches(
    image: np.ndarray,
    matches: list[Match],
    base_color: tuple[int, int, int] = (0, 255, 0),
) -> np.ndarray:
    canvas = image.copy()
    for index, match in enumerate(matches):
        color = (
            base_color
            if index == 0
            else (int(base_color[0]), int(base_color[1] * 0.7), 255)
        )
        rect = match.rect
        if rect.width <= 1 and rect.height <= 1:
            cv2.circle(canvas, (rect.x, rect.y), 12, color, 2)
            cv2.line(canvas, (rect.x - 18, rect.y), (rect.x + 18, rect.y), color, 2)
            cv2.line(canvas, (rect.x, rect.y - 18), (rect.x, rect.y + 18), color, 2)
        else:
            cv2.rectangle(
                canvas,
                (rect.x, rect.y),
                (max(rect.x, rect.right - 1), max(rect.y, rect.bottom - 1)),
                color,
                3,
            )
        label = f"{match.name} {match.score:.2f}"
        if match.text:
            label += f" {match.text}"
        label_y = rect.y - 8 if rect.y > 30 else rect.bottom + 26
        cv2.putText(
            canvas,
            label,
            (rect.x, label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
            cv2.LINE_AA,
        )
    return canvas
