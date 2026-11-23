from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError

_MISSING = object()


class Config:
    def __init__(self, data: dict[str, Any], path: Path | None = None) -> None:
        self.data = data
        self.path = path

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        target = Path(path).expanduser().resolve()
        if not target.exists():
            raise ConfigError(f"配置文件不存在: {target}")
        with target.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"配置文件必须是 YAML 对象: {target}")
        return cls(data, target)

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path | None = None) -> "Config":
        return cls(data, path)

    def get(self, dotted: str, default: Any = _MISSING) -> Any:
        current: Any = self.data
        for part in dotted.split("."):
            if not isinstance(current, dict) or part not in current:
                if default is _MISSING:
                    raise ConfigError(f"缺少配置项: {dotted}")
                return default
            current = current[part]
        return current

    def section(self, dotted: str) -> dict[str, Any]:
        value = self.get(dotted, {})
        if not isinstance(value, dict):
            raise ConfigError(f"配置项 {dotted} 必须是对象")
        return value

    def require(self, dotted: str) -> Any:
        return self.get(dotted)

    def resolve_path(self, value: str | Path) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return (Path.cwd() / path).resolve()

    def validate_core(self) -> list[str]:
        issues: list[str] = []
        capture_backend = self.get("capture.backend", "adb")
        if capture_backend not in ("adb", "folder", "static"):
            issues.append(f"capture.backend 无效: {capture_backend}")
        if capture_backend == "folder" and not self.get("capture.folder", None):
            issues.append("capture.backend 为 folder 时必须设置 capture.folder")
        control_backend = self.get("control.backend", "adb")
        if control_backend not in ("adb", "none"):
            issues.append(f"control.backend 无效: {control_backend}")
        if not self.get("vision.assets", None):
            issues.append("缺少 vision.assets")
        size = self.get("vision.canonical_size", [1920, 1080])
        if not isinstance(size, (list, tuple)) or len(size) != 2:
            issues.append("vision.canonical_size 必须是 [宽, 高]")
        task = self.get("task.name", None)
        if not task:
            issues.append("缺少 task.name")
        return issues
