from __future__ import annotations

import json
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .errors import (
    CaptureError,
    ConfigError,
    DeviceError,
    FrameStaleError,
    MissingAssetError,
    OcrUnavailable,
    RecognitionTimeout,
    StopRequested,
    TaskError,
)
from .result import Match

SCHEMA_VERSION = 1


class EventType(str, Enum):
    SESSION = "session"
    CAPTURE = "capture"
    RECOGNITION = "recognition"
    TAP = "tap"
    STATE = "state"
    ERROR = "error"
    TASK = "task"


class ErrorCode(str, Enum):
    NONE = ""
    DEVICE_UNAVAILABLE = "device_unavailable"
    CAPTURE_FAILED = "capture_failed"
    ASSET_MISSING = "asset_missing"
    OCR_UNAVAILABLE = "ocr_unavailable"
    RECOGNITION_MISS = "recognition_miss"
    STATE_UNKNOWN = "state_unknown"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    CONFIG_INVALID = "config_invalid"
    FRAME_STALE = "frame_stale"
    STORAGE_FAILED = "storage_failed"
    TASK_ERROR = "task_error"
    INTERNAL_ERROR = "internal_error"


_ERROR_CODES = (
    (MissingAssetError, ErrorCode.ASSET_MISSING),
    (OcrUnavailable, ErrorCode.OCR_UNAVAILABLE),
    (RecognitionTimeout, ErrorCode.TIMEOUT),
    (StopRequested, ErrorCode.CANCELLED),
    (FrameStaleError, ErrorCode.FRAME_STALE),
    (CaptureError, ErrorCode.CAPTURE_FAILED),
    (DeviceError, ErrorCode.DEVICE_UNAVAILABLE),
    (ConfigError, ErrorCode.CONFIG_INVALID),
    (TaskError, ErrorCode.TASK_ERROR),
    (OSError, ErrorCode.STORAGE_FAILED),
)


def classify_error(exc: BaseException) -> ErrorCode:
    for error_type, code in _ERROR_CODES:
        if isinstance(exc, error_type):
            return code
    return ErrorCode.INTERNAL_ERROR


@dataclass
class Event:
    event_type: str
    timestamp: float
    monotonic: float
    run_id: str = ""
    frame_id: str | None = None
    recognition_id: str | None = None
    name: str | None = None
    status: str | None = None
    score: float | None = None
    threshold: float | None = None
    bbox: list[int] | None = None
    duration_ms: float | None = None
    error_code: str = ""
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "event_type": self.event_type,
            "timestamp": round(self.timestamp, 3),
            "monotonic": round(self.monotonic, 6),
            "run_id": self.run_id,
        }
        optional = {
            "frame_id": self.frame_id,
            "recognition_id": self.recognition_id,
            "name": self.name,
            "status": self.status,
            "score": None if self.score is None else round(float(self.score), 4),
            "threshold": self.threshold,
            "bbox": self.bbox,
            "duration_ms": None
            if self.duration_ms is None
            else round(float(self.duration_ms), 3),
            "error_code": self.error_code,
            "message": self.message,
            "detail": self.detail,
        }
        for key, value in optional.items():
            if value not in (None, "", {}):
                data[key] = value
        return data

    def to_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class EventLog:
    def __init__(
        self,
        run_id: str,
        path: str | Path | None = None,
        max_events: int = 2000,
        clock=time.time,
        monotonic=time.monotonic,
    ) -> None:
        self.run_id = run_id
        self.max_events = max(1, int(max_events))
        self.clock = clock
        self.monotonic = monotonic
        self._events: deque[Event] = deque(maxlen=self.max_events)
        self._lock = threading.Lock()
        self._counter = 0
        self._dropped = 0
        self._handle = None
        if path is not None:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            self.path = target
            self._handle = target.open("a", encoding="utf-8")
        else:
            self.path = None

    @property
    def dropped(self) -> int:
        return self._dropped

    def __len__(self) -> int:
        return len(self._events)

    def next_recognition_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"{self.run_id}-r{self._counter:06d}"

    def emit(
        self,
        event_type: EventType | str,
        *,
        frame_id: str | None = None,
        recognition_id: str | None = None,
        name: str | None = None,
        status: str | None = None,
        score: float | None = None,
        threshold: float | None = None,
        bbox: list[int] | None = None,
        duration_ms: float | None = None,
        error_code: ErrorCode | str | None = None,
        message: str = "",
        detail: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            event_type=EventType(event_type).value,
            timestamp=float(self.clock()),
            monotonic=float(self.monotonic()),
            run_id=self.run_id,
            frame_id=frame_id,
            recognition_id=recognition_id,
            name=name,
            status=status,
            score=score,
            threshold=threshold,
            bbox=list(bbox) if bbox is not None else None,
            duration_ms=duration_ms,
            error_code=ErrorCode(error_code).value if error_code else "",
            message=message,
            detail=dict(detail or {}),
        )
        with self._lock:
            if len(self._events) == self.max_events:
                self._dropped += 1
            self._events.append(event)
            if self._handle is not None:
                self._handle.write(event.to_line() + "\n")
                self._handle.flush()
        return event

    def recognition(
        self,
        name: str,
        match: Match | None,
        *,
        frame_id: str | None,
        duration_ms: float,
        status: str | None = None,
        error_code: ErrorCode | str | None = None,
        message: str = "",
        detail: dict[str, Any] | None = None,
    ) -> Event:
        recognition_id = self.next_recognition_id()
        effective_status = status
        if effective_status is None:
            if match is None:
                effective_status = "miss"
            else:
                effective_status = getattr(match.status, "value", str(match.status))
        if error_code is None and match is None:
            error_code = ErrorCode.RECOGNITION_MISS
        return self.emit(
            EventType.RECOGNITION,
            frame_id=frame_id if frame_id is not None else (match.frame_id if match else None),
            recognition_id=recognition_id,
            name=name,
            status=effective_status,
            score=match.score if match else None,
            threshold=match.threshold if match else None,
            bbox=match.rect.to_list() if match else None,
            duration_ms=duration_ms,
            error_code=error_code,
            message=message,
            detail=detail,
        )

    def error(
        self,
        exc: BaseException,
        *,
        frame_id: str | None = None,
        event_type: EventType | str = EventType.ERROR,
        message: str = "",
    ) -> Event:
        code = classify_error(exc)
        return self.emit(
            event_type,
            frame_id=frame_id,
            error_code=code,
            message=message or str(exc),
            detail={"exception": type(exc).__name__},
        )

    def error_counts(self) -> dict[str, int]:
        with self._lock:
            counts = Counter(
                event.error_code for event in self._events if event.error_code
            )
        return dict(sorted(counts.items()))

    def recent(self, limit: int = 50) -> list[Event]:
        with self._lock:
            items = list(self._events)
        return items[-limit:]

    def to_list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [event.to_dict() for event in self._events]

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.close()
                self._handle = None


def classify_exception(exc: BaseException) -> str:
    return classify_error(exc).value
