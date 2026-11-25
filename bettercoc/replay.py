from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .errors import BetterCoCError
from .frame import Frame
from .geometry import Viewport
from .image import load_image
from .jsonio import read_json, read_jsonl, write_json_atomic
from .recorder import asset_fingerprint, load_session_manifest
from .vision import Vision

SCORE_TOLERANCE = 1e-3


@dataclass
class ReplayedFrame:
    frame: Frame
    file: Path
    meta: dict[str, Any]


class ReplaySession:
    def __init__(self, path: str | Path) -> None:
        self.manifest = load_session_manifest(path)
        self.root = Path(self.manifest["_dir"])
        self.events = read_jsonl(self.root / "events.jsonl")
        self.report = read_json(self.root / "report.json", {}) or {}
        self.recorded_assets = dict(self.manifest.get("assets_fingerprint") or {})

    @classmethod
    def load(cls, path: str | Path) -> "ReplaySession":
        return cls(path)

    @property
    def run_id(self) -> str:
        return str(self.manifest.get("run_id", ""))

    @property
    def canonical(self) -> tuple[int, int]:
        size = self.manifest.get("canonical_size", [1920, 1080])
        return int(size[0]), int(size[1])

    def frames(self) -> list[ReplayedFrame]:
        items: list[ReplayedFrame] = []
        for meta in self.manifest.get("frames", []):
            relative = meta.get("file")
            if not relative:
                continue
            path = self.root / str(relative)
            if not path.exists():
                raise BetterCoCError(f"回放缺少帧文件: {path}")
            image = load_image(path)
            viewport_data = meta.get("viewport") or {}
            raw_size = meta.get("raw_size") or [
                viewport_data.get("device_width", image.shape[1]),
                viewport_data.get("device_height", image.shape[0]),
            ]
            viewport = Viewport(
                device_width=int(raw_size[0]),
                device_height=int(raw_size[1]),
                canonical_width=int(self.canonical[0]),
                canonical_height=int(self.canonical[1]),
            )
            frame = Frame(
                frame_id=str(meta.get("frame_id") or path.stem),
                source_id=str(meta.get("source_id") or "replay"),
                image=image,
                viewport=viewport,
                raw_size=(int(raw_size[0]), int(raw_size[1])),
                captured_at=time.monotonic(),
                captured_wall=time.time(),
                sequence=int(meta.get("sequence") or len(items) + 1),
                stale_after=10_000.0,
            )
            items.append(ReplayedFrame(frame=frame, file=path, meta=meta))
        if not items:
            raise BetterCoCError(f"回放会话没有可用帧: {self.root}")
        return items

    def asset_drift(self, vision: Vision) -> dict[str, Any]:
        current = asset_fingerprint(vision)
        recorded = self.recorded_assets
        changed = bool(recorded) and (
            recorded.get("manifest_sha256") != current.get("manifest_sha256")
            or recorded.get("templates_sha256") != current.get("templates_sha256")
        )
        return {
            "changed": changed,
            "recorded_manifest_sha256": recorded.get("manifest_sha256"),
            "current_manifest_sha256": current.get("manifest_sha256"),
            "recorded_templates_sha256": recorded.get("templates_sha256"),
            "current_templates_sha256": current.get("templates_sha256"),
        }

    def recorded_results(self) -> dict[tuple[str, str], dict[str, Any]]:
        results: dict[tuple[str, str], dict[str, Any]] = {}
        for event in self.events:
            if event.get("event_type") != "recognition":
                continue
            frame_id = str(event.get("frame_id") or "")
            name = str(event.get("name") or "")
            if not frame_id or not name:
                continue
            results[(frame_id, name)] = event
        return results

    def run(
        self,
        vision: Vision,
        names: Iterable[str] | None = None,
        tolerance: float = SCORE_TOLERANCE,
    ) -> dict[str, Any]:
        targets = list(names) if names is not None else vision.assets.names()
        recorded = self.recorded_results()
        frames_report: list[dict[str, Any]] = []
        mismatches: list[dict[str, Any]] = []
        comparisons = 0
        for item in self.frames():
            frame = item.frame
            screen = frame.to_screen()
            checks: list[dict[str, Any]] = []
            for name in targets:
                started = time.perf_counter()
                match = None
                error = None
                try:
                    match = vision.find(screen, name)
                except Exception as exc:
                    error = exc
                duration_ms = (time.perf_counter() - started) * 1000.0
                status = getattr(match.status, "value", "matched") if match else "miss"
                result = {
                    "name": name,
                    "status": status,
                    "score": None if match is None else round(float(match.score), 6),
                    "rect": None if match is None else match.rect.to_list(),
                    "text": None if match is None else match.text,
                    "duration_ms": round(duration_ms, 3),
                    "error": None if error is None else type(error).__name__,
                }
                checks.append(result)
                previous = recorded.get((frame.frame_id, name))
                if previous is not None:
                    comparisons += 1
                    previous_status = str(previous.get("status") or "")
                    previous_score = previous.get("score")
                    status_changed = previous_status != status
                    score_changed = False
                    if previous_score is not None and result["score"] is not None:
                        score_changed = (
                            abs(float(previous_score) - float(result["score"]))
                            > tolerance
                        )
                    bbox_changed = previous.get("bbox") is not None and result["rect"] != previous.get("bbox")
                    if status_changed or score_changed or bbox_changed:
                        mismatches.append(
                            {
                                "frame_id": frame.frame_id,
                                "name": name,
                                "recorded_status": previous_status,
                                "replayed_status": status,
                                "recorded_score": previous_score,
                                "replayed_score": result["score"],
                                "status_changed": status_changed,
                                "score_changed": score_changed,
                                "bbox_changed": bbox_changed,
                            }
                        )
            frames_report.append(
                {
                    "frame_id": frame.frame_id,
                    "file": str(item.meta.get("file")),
                    "label": item.meta.get("label"),
                    "checks": checks,
                }
            )
        drift = self.asset_drift(vision)
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "session": str(self.root),
            "canonical_size": list(self.canonical),
            "recognition": targets,
            "score_tolerance": tolerance,
            "assets_drift": drift,
            "assets_changed": drift["changed"],
            "frames": frames_report,
            "comparisons": comparisons,
            "mismatches": mismatches,
            "summary": {
                "frames": len(frames_report),
                "checks": sum(len(item["checks"]) for item in frames_report),
                "comparisons": comparisons,
                "mismatches": len(mismatches),
            },
        }

    def write_report(self, path: str | Path, data: dict[str, Any]) -> Path:
        return write_json_atomic(path, data)
