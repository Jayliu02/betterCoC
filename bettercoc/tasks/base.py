from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..context import Context


@dataclass
class TaskResult:
    task: str
    status: str
    reason: str
    counters: dict[str, int] = field(default_factory=dict)
    elapsed: float = 0.0
    transitions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "status": self.status,
            "reason": self.reason,
            "counters": self.counters,
            "elapsed": round(self.elapsed, 2),
            "transitions": self.transitions,
        }


class Task(ABC):
    name = "task"

    @abstractmethod
    def run(self, ctx: Context) -> TaskResult:
        raise NotImplementedError
