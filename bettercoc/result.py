from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .geometry import Rect


class RecognitionStatus(str, Enum):
    MATCHED = "matched"
    MISS = "miss"
    COORDINATE_ONLY = "coordinate_only"
    UNKNOWN = "unknown"


@dataclass
class Match:
    rect: Rect
    score: float = 1.0
    text: str | None = None
    name: str = ""
    frame_id: str | None = None
    threshold: float | None = None
    status: RecognitionStatus = RecognitionStatus.MATCHED

    @property
    def center(self) -> tuple[int, int]:
        return self.rect.center

    @property
    def is_visual_evidence(self) -> bool:
        return self.status is RecognitionStatus.MATCHED

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "rect": self.rect.to_list(),
            "score": round(float(self.score), 4),
            "text": self.text,
            "frame_id": self.frame_id,
            "threshold": self.threshold,
            "status": self.status.value,
        }
