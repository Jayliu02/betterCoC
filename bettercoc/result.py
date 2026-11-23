from __future__ import annotations

from dataclasses import dataclass

from .geometry import Rect


@dataclass
class Match:
    rect: Rect
    score: float = 1.0
    text: str | None = None
    name: str = ""

    @property
    def center(self) -> tuple[int, int]:
        return self.rect.center
