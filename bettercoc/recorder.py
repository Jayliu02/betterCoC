from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .errors import BetterCoCError
from .events import SCHEMA_VERSION as EVENT_SCHEMA_VERSION
from .events import ErrorCode, Event, EventLog
from .frame import Frame
from .image import load_image, normalize_frame, save_image
from .jsonio import read_json, write_json_atomic
from .vision import Vision

SESSION_SCHEMA_VERSION = 1
SAFE_NAME = re.compile(r"[^0-9A-Za-z._-]+")


def safe_name(value: str, limit: int = 80) -> str:
    cleaned = SAFE_NAME.sub("_", str(value)).strip("._-")
    return (cleaned or "frame")[:limit]


@dataclass
class RecorderLimits:
    max_frames: int = 200
    max_events: int = 5000
    max_frame_bytes: int = 200 * 1024 * 1024


@dataclass
class RecorderCounters:
    frames: int = 0
    frames_skipped: int = 0
    events: int = 0
    bytes_written: int = 0
    truncated: bool = False


class Recorder:
    def __init__(
        self,
        root: str | Path,
        run_id: str | None = None,
        canonical: tuple[int, int] = (1920, 1080),
        source_id: str = "",
        limits: RecorderLimits | None = None,
        clock=time.time,
    ) -> None:
        self.root = Path(root)
        self.run_id = run_id or (
            time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        )
        self.session_dir = self.root / self.run_id
        self.frames_dir = self.session_dir / "frames"
        self.canonical = (int(canonical[0]), int(canonical[1]))
        self.source_id = source_id
        self.limits = limits or RecorderLimits()
        self.clock = clock
        self.counters = RecorderCounters()
        self.started_at = float(clock())
        self.finished_at: float | None = None
        self.status = "recording"
        self.reason = ""
        self._frames: list[dict[str, Any]] = []
        self._extra: dict[str, Any] = {}
        self.events = EventLog(
            self.run_id,
            path=self.session_dir / "events.jsonl",
            max_events=self.limits.max_events,
        )
        self._manifest: dict[str, Any] = {}

    def start(
        self,
        config=None,
        assets_manifest: str | Path | None = None,
        assets_fingerprint: dict[str, Any] | None = None,
        note: str = "",
    ) -> Path:
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        try:
            resolved = str(Path(assets_manifest).resolve()) if assets_manifest else None
        except OSError:
            resolved = None
        self._manifest = {
            "schema_version": SESSION_SCHEMA_VERSION,
            "run_id": self.run_id,
            "created_at": self.clock(),
            "created_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
            "canonical_size": list(self.canonical),
            "source_id": self.source_id,
            "note": note,
            "assets_manifest": resolved,
            "assets_fingerprint": dict(assets_fingerprint or {}),
            "config": self._config_snapshot(config),
            "limits": {
                "max_frames": self.limits.max_frames,
                "max_events": self.limits.max_events,
                "max_frame_bytes": self.limits.max_frame_bytes,
            },
            "event_schema_version": EVENT_SCHEMA_VERSION,
            "frames": self._frames,
        }
        self._write_manifest()
        self.events.emit(
            "session",
            message="开始录制",
            detail={"source_id": self.source_id, "note": note},
        )
        return self.session_dir

    @staticmethod
    def _config_snapshot(config) -> dict[str, Any]:
        if config is None:
            return {}
        snapshot: dict[str, Any] = {"path": str(config.path) if config.path else None}
        for key in (
            "capture.backend",
            "control.backend",
            "vision.assets",
            "vision.digits",
            "vision.canonical_size",
            "runtime.dry_run",
        ):
            try:
                snapshot[key] = config.get(key, None)
            except Exception:
                snapshot[key] = None
        return snapshot

    def record_frame(self, frame: Frame, label: str = "") -> Path | None:
        if self.counters.frames >= self.limits.max_frames:
            self.counters.truncated = True
            self.counters.frames_skipped += 1
            self.events.emit(
                "capture",
                frame_id=frame.frame_id,
                status="skipped",
                error_code=ErrorCode.STORAGE_FAILED,
                message="超过录制帧数上限，跳过保存",
            )
            return None
        target = self.frames_dir / f"{safe_name(frame.frame_id)}-{self.counters.frames + 1:03d}.png"
        save_image(target, frame.image)
        size = int(target.stat().st_size)
        if (
            self.counters.bytes_written + size > self.limits.max_frame_bytes
            and self.counters.frames > 0
        ):
            target.unlink(missing_ok=True)
            self.counters.truncated = True
            self.counters.frames_skipped += 1
            self.events.emit(
                "capture",
                frame_id=frame.frame_id,
                status="skipped",
                error_code=ErrorCode.STORAGE_FAILED,
                message="超过录制体积上限，跳过保存",
            )
            return None
        metadata = frame.to_dict()
        metadata["file"] = str(target.relative_to(self.session_dir)).replace("\\", "/")
        metadata["bytes"] = size
        metadata["label"] = label
        self._frames.append(metadata)
        self.counters.frames += 1
        self.counters.bytes_written += size
        self._write_manifest()
        return target

    def record_frame_event(self, frame: Frame) -> Event:
        event = self.events.emit(
            "capture",
            frame_id=frame.frame_id,
            status="recorded",
            duration_ms=None,
            detail=frame.to_dict(),
        )
        self.counters.events += 1
        return event

    def recognize(
        self,
        vision: Vision,
        frame: Frame,
        names: Iterable[str] | None = None,
        limits_note: str = "",
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        targets = list(names) if names is not None else vision.assets.names()
        for name in targets:
            started = time.perf_counter()
            match = None
            error: BaseException | None = None
            try:
                match = vision.find(frame.to_screen(), name)
            except Exception as exc:
                error = exc
            duration_ms = (time.perf_counter() - started) * 1000.0
            event = self.events.recognition(
                name,
                match,
                frame_id=frame.frame_id,
                duration_ms=duration_ms,
                message=limits_note,
            )
            if error is not None:
                self.events.error(error, frame_id=frame.frame_id)
            self.counters.events += 1
            results.append(
                {
                    "name": name,
                    "frame_id": frame.frame_id,
                    "status": getattr(match.status, "value", "matched")
                    if match
                    else "miss",
                    "score": None if match is None else round(float(match.score), 4),
                    "rect": None if match is None else match.rect.to_list(),
                    "text": None if match is None else match.text,
                    "duration_ms": round(duration_ms, 3),
                    "event_id": event.recognition_id,
                    "error": None if error is None else type(error).__name__,
                }
            )
        return results

    def finish(self, status: str = "completed", reason: str = "", extra: dict | None = None) -> Path:
        self.status = status
        self.reason = reason
        self.finished_at = float(self.clock())
        if extra:
            self._extra.update(extra)
        self.events.emit(
            "session",
            status=status,
            message=reason or "录制结束",
            detail={"frames": self.counters.frames},
        )
        report = self.report()
        write_json_atomic(self.session_dir / "report.json", report)
        self.events.close()
        return self.session_dir

    def report(self) -> dict[str, Any]:
        ended = self.finished_at if self.finished_at is not None else float(self.clock())
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": self.status,
            "reason": self.reason,
            "started_at": round(self.started_at, 3),
            "finished_at": round(ended, 3),
            "duration_s": round(max(0.0, ended - self.started_at), 3),
            "frames": self.counters.frames,
            "frames_skipped": self.counters.frames_skipped,
            "events_recorded": self.counters.events,
            "events_dropped": self.events.dropped,
            "bytes_written": self.counters.bytes_written,
            "truncated": self.counters.truncated,
            "error_counts": self.events.error_counts(),
            "limits": {
                "max_frames": self.limits.max_frames,
                "max_events": self.limits.max_events,
                "max_frame_bytes": self.limits.max_frame_bytes,
            },
            "extra": self._extra,
        }

    def _write_manifest(self) -> None:
        self._manifest["frames"] = self._frames
        self._manifest["status"] = self.status
        write_json_atomic(self.session_dir / "manifest.json", self._manifest)

    def close(self) -> None:
        self.events.close()


def load_session_manifest(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if target.is_dir():
        target = target / "manifest.json"
    data = read_json(target)
    if not isinstance(data, dict) or not data.get("frames"):
        raise BetterCoCError(f"录制会话清单无效: {target}")
    data["_path"] = str(target)
    data["_dir"] = str(target.parent)
    return data


def asset_fingerprint(vision: Vision) -> dict[str, Any]:
    store = vision.assets
    manifest = Path(store.manifest_path)
    templates = sorted(store.template_root.glob("*.png"))
    digest = hashlib.sha256()
    for path in templates:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return {
        "manifest": str(manifest),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()
        if manifest.exists()
        else None,
        "template_count": len(templates),
        "templates_sha256": digest.hexdigest(),
    }


def record_live_session(
    capture,
    vision: Vision,
    output_root: str | Path,
    frame_count: int = 5,
    names: Iterable[str] | None = None,
    canonical: tuple[int, int] = (1920, 1080),
    source_id: str | None = None,
    note: str = "",
    stale_after: float = 2.0,
) -> Recorder:
    from .frame import FrameProvider

    provider = FrameProvider(
        capture, canonical=canonical, source_id=source_id, stale_after=stale_after
    )
    recorder = Recorder(
        output_root,
        canonical=canonical,
        source_id=provider.source_id,
        limits=RecorderLimits(max_frames=max(1, frame_count)),
    )
    recorder.start(
        assets_manifest=str(vision.assets.manifest_path),
        assets_fingerprint=asset_fingerprint(vision),
        note=note or "live session",
    )
    recorded = 0
    for index in range(max(1, frame_count)):
        try:
            frame = provider.capture()
        except Exception as exc:
            recorder.events.error(exc, message="录制时截图失败")
            recorder.finish(status="failed", reason=str(exc))
            return recorder
        recorder.record_frame_event(frame)
        if recorder.record_frame(frame) is None:
            continue
        recorder.recognize(vision, frame, names=names)
        recorded += 1
        if index + 1 < frame_count:
            time.sleep(0.2)
    recorder.finish(status="completed", reason=f"录制 {recorded} 帧")
    return recorder


def record_fixture_session(
    fixture_manifest: dict[str, Any],
    vision: Vision,
    output_root: str | Path,
    frame_limit: int = 8,
    names: Iterable[str] | None = None,
) -> Recorder:
    base = Path(fixture_manifest["_dir"])
    size = fixture_manifest.get("canonical_size", [1920, 1080])
    canonical = (int(size[0]), int(size[1]))
    recorder = Recorder(
        output_root,
        canonical=canonical,
        source_id="fixtures",
        limits=RecorderLimits(max_frames=max(1, frame_limit)),
    )
    recorder.start(
        assets_manifest=str(vision.assets.manifest_path),
        assets_fingerprint=asset_fingerprint(vision),
        note=f"fixture session: {fixture_manifest.get('_path')}",
    )
    recorded = 0
    for entry in fixture_manifest["frames"]:
        if recorded >= frame_limit:
            break
        image = load_image(base / entry["file"])
        screen = normalize_frame(image, canonical)
        frame = Frame(
            frame_id=str(entry["id"]),
            source_id="fixtures",
            image=screen.image,
            viewport=screen.viewport,
            raw_size=(image.shape[1], image.shape[0]),
            captured_at=time.monotonic(),
            captured_wall=time.time(),
            sequence=recorded + 1,
            stale_after=10_000.0,
        )
        recorder.record_frame_event(frame)
        target = recorder.record_frame(frame, label=str(entry.get("id")))
        if target is None:
            continue
        recorder.recognize(vision, frame, names=names)
        recorded += 1
    recorder.finish(status="completed", reason=f"录制 {recorded} 帧")
    return recorder
