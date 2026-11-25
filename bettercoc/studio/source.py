from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..baseline import load_fixture_manifest
from ..errors import BetterCoCError
from ..frame import Frame
from ..image import load_image, normalize_frame
from ..jsonio import read_json, read_jsonl
from ..replay import ReplaySession


@dataclass
class StudioFrame:
    index: int
    frame: Frame
    label: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)


class StudioSource:
    name = "source"
    description = ""
    readonly = True

    def frame_count(self) -> int:
        raise NotImplementedError

    def frame(self, index: int) -> StudioFrame:
        raise NotImplementedError

    def assets(self) -> list[str]:
        return []

    def events(self) -> list[dict[str, Any]]:
        return []

    def close(self) -> None:
        return None


class FixtureSource(StudioSource):
    name = "固定测试集"

    def __init__(self, fixture_dir: str | Path) -> None:
        self.manifest = load_fixture_manifest(fixture_dir)
        self.base = Path(self.manifest["_dir"])
        size = self.manifest.get("canonical_size", [1920, 1080])
        self.canonical = (int(size[0]), int(size[1]))
        self.description = str(self.manifest["_path"])
        self._frames = list(self.manifest["frames"])

    def frame_count(self) -> int:
        return len(self._frames)

    def frame(self, index: int) -> StudioFrame:
        entry = self._frames[index]
        image = load_image(self.base / str(entry["file"]))
        screen = normalize_frame(image, self.canonical)
        frame = Frame(
            frame_id=str(entry["id"]),
            source_id="fixtures",
            image=screen.image,
            viewport=screen.viewport,
            raw_size=(
                int(entry.get("stored", {}).get("width", image.shape[1])),
                int(entry.get("stored", {}).get("height", image.shape[0])),
            ),
            captured_at=time.monotonic(),
            captured_wall=time.time(),
            sequence=index + 1,
            stale_after=10_000.0,
        )
        return StudioFrame(
            index=index,
            frame=frame,
            label=str(entry.get("state") or entry["id"]),
        )

    def assets(self) -> list[str]:
        names: set[str] = set()
        for entry in self._frames:
            names.update(str(name) for name in (entry.get("labels") or {}))
        return sorted(names)

    def expectations(self, frame_id: str) -> dict[str, str]:
        for entry in self._frames:
            if str(entry["id"]) == frame_id:
                return dict(entry.get("labels") or {})
        return {}


class SessionSource(StudioSource):
    name = "录制会话"

    def __init__(self, session_dir: str | Path) -> None:
        self.session = ReplaySession.load(session_dir)
        self.canonical = self.session.canonical
        self.description = str(self.session.root)
        self._replayed = self.session.frames()
        self._events = self.session.events
        self._by_frame: dict[str, list[dict[str, Any]]] = {}
        for event in self._events:
            frame_id = str(event.get("frame_id") or "")
            if frame_id:
                self._by_frame.setdefault(frame_id, []).append(event)

    def frame_count(self) -> int:
        return len(self._replayed)

    def frame(self, index: int) -> StudioFrame:
        item = self._replayed[index]
        frame = item.frame
        frame.captured_at = time.monotonic()
        return StudioFrame(
            index=index,
            frame=frame,
            label=str(item.meta.get("label") or frame.frame_id),
            events=list(self._by_frame.get(frame.frame_id, [])),
        )

    def assets(self) -> list[str]:
        names = {str(event.get("name")) for event in self._events if event.get("name")}
        return sorted(names)

    def events(self) -> list[dict[str, Any]]:
        return self._events


class LiveSource(StudioSource):
    name = "设备只读预览"

    def __init__(self, capture, canonical: tuple[int, int] = (1920, 1080)) -> None:
        self.provider = _provider(capture, canonical)
        self.canonical = canonical
        self.description = getattr(capture, "description", "live")
        self._count = 0
        self._last: StudioFrame | None = None

    def frame_count(self) -> int:
        return max(1, self._count)

    def frame(self, index: int) -> StudioFrame:
        if self._last is not None and index == self._last.index:
            return self._last
        frame = self.provider.capture()
        self._count += 1
        item = StudioFrame(index=index, frame=frame, label=f"实时 {self._count}")
        self._last = item
        return item

    def refresh(self) -> StudioFrame:
        frame = self.provider.capture()
        self._count += 1
        item = StudioFrame(index=self._count - 1, frame=frame, label=f"实时 {self._count}")
        self._last = item
        return item

    def age(self) -> float | None:
        if self._last is None:
            return None
        return self._last.frame.age()

    def close(self) -> None:
        closer = getattr(self.provider.source, "close", None)
        if callable(closer):
            closer()


def _provider(capture, canonical):
    from ..frame import FrameProvider

    return FrameProvider(capture, canonical=canonical, stale_after=60.0)


def open_source(path: str | Path | None) -> StudioSource:
    if path is None:
        raise BetterCoCError("未指定 Studio 数据源")
    target = Path(path)
    if not target.exists():
        raise BetterCoCError(f"数据源不存在: {target}")
    manifest_path = target / "manifest.json" if target.is_dir() else target
    data = read_json(manifest_path, {}) or {}
    if not isinstance(data, dict) or not data.get("frames"):
        raise BetterCoCError(f"无法识别数据源: {target}")
    if read_json(target / "report.json", None) is not None or data.get("run_id"):
        return SessionSource(target)
    return FixtureSource(target)


def load_events(path: str | Path) -> list[dict[str, Any]]:
    return read_jsonl(path)
