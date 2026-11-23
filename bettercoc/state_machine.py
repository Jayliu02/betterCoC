from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from .errors import StopRequested, TaskError


@dataclass
class State:
    name: str
    handler: Callable[[], str | None]
    on_error: str | None = None


@dataclass
class Transition:
    source: str
    target: str
    elapsed: float


class StateMachine:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.states: dict[str, State] = {}
        self.transitions: list[Transition] = []
        self.last_error: Exception | None = None

    def add(
        self,
        name: str,
        handler: Callable[[], str | None],
        on_error: str | None = None,
    ) -> "StateMachine":
        if name in self.states:
            raise TaskError(f"重复的状态名: {name}")
        self.states[name] = State(name=name, handler=handler, on_error=on_error)
        return self

    def run(self, initial: str, max_steps: int = 500) -> str:
        if initial not in self.states:
            raise TaskError(f"未知初始状态: {initial}")
        current = initial
        for step in range(1, max_steps + 1):
            state = self.states[current]
            self.logger.info("状态 [%d] %s", step, current)
            started = time.monotonic()
            try:
                target = state.handler()
            except StopRequested:
                raise
            except Exception as exc:
                self.last_error = exc
                if state.on_error is None:
                    raise
                self.logger.exception("状态 %s 失败，转入 %s", current, state.on_error)
                target = state.on_error
            elapsed = time.monotonic() - started
            if target is None:
                return current
            if target not in self.states:
                raise TaskError(f"状态 {current} 返回了未知状态: {target}")
            self.transitions.append(Transition(current, target, elapsed))
            self.logger.debug("转移 %s -> %s (%.2fs)", current, target, elapsed)
            current = target
        raise TaskError(f"状态机超过最大步数 {max_steps}，最后状态 {current}")
