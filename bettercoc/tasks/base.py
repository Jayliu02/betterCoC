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
    started_at: float = 0.0

    def _begin(self, ctx: Context) -> None:
        self.started_at = ctx.clock()

    def _task_elapsed(self, ctx: Context) -> float:
        return max(0.0, ctx.clock() - self.started_at)

    def _runtime_exceeded(self, ctx: Context, minutes: float) -> bool:
        return minutes > 0 and self._task_elapsed(ctx) >= minutes * 60

    @abstractmethod
    def run(self, ctx: Context) -> TaskResult:
        raise NotImplementedError
