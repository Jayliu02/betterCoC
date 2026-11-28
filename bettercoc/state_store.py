from __future__ import annotations

import time
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

from .errors import BetterCoCError
from .jsonio import read_json, write_json_atomic

STATE_SCHEMA_VERSION = 1
LEGACY_FIELDS = (
    "gold",
    "elixir",
    "dark",
    "gold_max",
    "elixir_max",
    "dark_max",
    "wall_remaining",
    "wall_upgraded",
    "wall_complete",
    "walls_done",
    "updated_at",
)


class StateError(BetterCoCError):
    pass


class StateSource(str, Enum):
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    CACHED = "cached"
    CONFIGURED = "configured"


class StateStatus(str, Enum):
    VALID = "valid"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass
class Observation:
    key: str
    value: int | None
    source: StateSource
    status: StateStatus
    observed_at: float | None = None
    frame_id: str | None = None
    reason: str = ""
    schema_version: int = STATE_SCHEMA_VERSION

    @property
    def is_missing(self) -> bool:
        return self.value is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "source": self.source.value,
            "status": self.status.value,
            "observed_at": None
            if self.observed_at is None
            else round(float(self.observed_at), 3),
            "frame_id": self.frame_id,
            "reason": self.reason,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, key: str, data: dict[str, Any]) -> "Observation":
        try:
            source = StateSource(str(data.get("source", "cached")))
        except ValueError:
            source = StateSource.CACHED
        try:
            status = StateStatus(str(data.get("status", "unknown")))
        except ValueError:
            status = StateStatus.UNKNOWN
        raw_value = data.get("value")
        value = None if raw_value is None else int(raw_value)
        observed_at = data.get("observed_at")
        return cls(
            key=key,
            value=value,
            source=source,
            status=status if value is not None else StateStatus.UNKNOWN,
            observed_at=None if observed_at is None else float(observed_at),
            frame_id=data.get("frame_id"),
            reason=str(data.get("reason", "")),
            schema_version=int(data.get("schema_version", STATE_SCHEMA_VERSION)),
        )


class StateStore:
    def __init__(
        self,
        path: str | Path | None = None,
        stale_after: float = 120.0,
        clock=time.time,
    ) -> None:
        self.path = Path(path) if path is not None else None
        self.stale_after = float(stale_after)
        self.clock = clock
        self._items: dict[str, Observation] = {}
        self.load_error: str | None = None
        self.loaded_legacy: bool = False

    def observe(
        self,
        key: str,
        value: int | None,
        frame_id: str | None = None,
        source: StateSource = StateSource.OBSERVED,
        reason: str = "",
    ) -> Observation:
        if value is None:
            observation = Observation(
                key=key,
                value=None,
                source=source,
                status=StateStatus.UNKNOWN,
                observed_at=float(self.clock()),
                frame_id=frame_id,
                reason=reason or "未观测到数值",
            )
        else:
            observation = Observation(
                key=key,
                value=int(value),
                source=source,
                status=StateStatus.VALID,
                observed_at=float(self.clock()),
                frame_id=frame_id,
                reason=reason,
            )
        self._items[key] = observation
        return observation

    def configured(self, key: str, value: int | None, reason: str = "配置兜底") -> Observation:
        return self.observe(key, value, source=StateSource.CONFIGURED, reason=reason)

    def estimate(
        self, key: str, value: int | None, reason: str = "基于上一次观测推算"
    ) -> Observation:
        return self.observe(key, value, source=StateSource.ESTIMATED, reason=reason)

    def fallback(self, key: str, value: int) -> Observation:
        existing = self.get(key)
        if existing is not None and existing.status is StateStatus.VALID:
            return existing
        return self.configured(key, value)

    def get(self, key: str) -> Observation | None:
        observation = self._items.get(key)
        if observation is None:
            return None
        if observation.status is StateStatus.VALID and observation.observed_at is not None:
            age = float(self.clock()) - observation.observed_at
            if age > self.stale_after:
                return replace(
                    observation,
                    status=StateStatus.STALE,
                    reason=observation.reason or f"观测已过期 {age:.0f}s",
                )
        return observation

    def value(self, key: str) -> int | None:
        observation = self.get(key)
        return None if observation is None else observation.value

    def keys(self) -> list[str]:
        return sorted(self._items)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {key: self.get(key).to_dict() for key in self.keys() if self.get(key)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "saved_at": round(float(self.clock()), 3),
            "states": self.snapshot(),
        }

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path is not None else self.path
        if target is None:
            raise StateError("未指定状态文件路径")
        try:
            return write_json_atomic(target, self.to_dict())
        except OSError as exc:
            raise StateError(f"写入状态文件失败: {target}: {exc}") from exc

    def load(self, path: str | Path | None = None) -> "StateStore":
        target = Path(path) if path is not None else self.path
        if target is None:
            raise StateError("未指定状态文件路径")
        self.path = target
        self.load_error = None
        self.loaded_legacy = False
        if not target.exists():
            return self
        data = read_json(target)
        if not isinstance(data, dict) or not data:
            self.load_error = f"状态文件无法解析: {target}"
            return self
        states = data.get("states")
        if isinstance(states, dict):
            for key, raw in states.items():
                if isinstance(raw, dict):
                    observation = Observation.from_dict(str(key), raw)
                    if observation.status is not StateStatus.UNKNOWN:
                        observation = replace(
                            observation,
                            reason=observation.reason or "从状态文件恢复",
                        )
                    self._items[str(key)] = observation
            return self
        self.loaded_legacy = True
        for key in LEGACY_FIELDS:
            if key not in data:
                continue
            raw_value = data.get(key)
            if raw_value is None or key == "updated_at":
                continue
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                continue
            self._items[key] = Observation(
                key=key,
                value=value,
                source=StateSource.CACHED,
                status=StateStatus.VALID,
                observed_at=None,
                reason="历史状态文件，无观测时间",
            )
        return self

    def capacity_check(self, value_key: str, limit_key: str) -> dict[str, Any]:
        value = self.get(value_key)
        limit = self.get(limit_key)
        result: dict[str, Any] = {
            "value_key": value_key,
            "limit_key": limit_key,
            "value": None if value is None else value.value,
            "limit": None if limit is None else limit.value,
            "status": "unknown",
            "reason": "",
        }
        if value is None or value.value is None:
            result["reason"] = "观测值缺失，不能与上限比较"
            return result
        if limit is None or limit.value is None:
            result["status"] = "unknown"
            result["reason"] = "上限缺失，不能判定余额是否合理"
            return result
        if value.value > limit.value:
            result["status"] = "over_capacity"
            result["reason"] = "余额超过已知上限，可能是上限未刷新或识别误差，不能直接判为错误"
            return result
        result["status"] = "within_capacity"
        return result
