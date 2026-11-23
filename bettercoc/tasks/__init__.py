from __future__ import annotations

from .base import Task, TaskResult
from .farm_wall import FarmWallTask
from .raid import RaidTask
from .wall_upgrade import WallUpgradeTask

TASKS = {
    "farm_wall": FarmWallTask,
    "raid": RaidTask,
    "wall_upgrade": WallUpgradeTask,
}


def create_task(name: str) -> Task:
    try:
        return TASKS[name]()
    except KeyError as exc:
        available = ", ".join(sorted(TASKS))
        raise ValueError(f"未知任务 {name}，可用: {available}") from exc


__all__ = [
    "Task",
    "TaskResult",
    "TASKS",
    "create_task",
    "FarmWallTask",
    "RaidTask",
    "WallUpgradeTask",
]
