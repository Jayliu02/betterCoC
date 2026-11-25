from __future__ import annotations

import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
import yaml

from ..frame import Frame
from ..geometry import Rect
from ..image import normalize_frame, save_image
from ..result import RecognitionStatus
from ..spec import Kind, Recognition
from ..template import Template, find_template
from ..vision import Vision


@dataclass
class RecognitionRow:
    name: str
    kind: str
    status: str
    score: float | None = None
    threshold: float | None = None
    rect: Rect | None = None
    text: str | None = None
    duration_ms: float = 0.0
    error: str | None = None

    @property
    def is_visual_evidence(self) -> bool:
        return self.status == RecognitionStatus.MATCHED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "score": None if self.score is None else round(self.score, 4),
            "threshold": self.threshold,
            "rect": None if self.rect is None else self.rect.to_list(),
            "text": self.text,
            "duration_ms": round(self.duration_ms, 3),
            "error": self.error,
        }


def recognize_frame(
    vision: Vision,
    frame: Frame,
    names: Iterable[str] | None = None,
) -> list[RecognitionRow]:
    screen = frame.to_screen()
    targets = list(names) if names is not None else vision.assets.names()
    rows: list[RecognitionRow] = []
    for name in targets:
        started = time.perf_counter()
        try:
            spec = vision.assets.recognition(name)
        except Exception as exc:
            rows.append(
                RecognitionRow(
                    name=name,
                    kind="unknown",
                    status=RecognitionStatus.UNKNOWN.value,
                    error=str(exc),
                )
            )
            continue
        try:
            match = vision.find(screen, spec)
        except Exception as exc:
            rows.append(
                RecognitionRow(
                    name=name,
                    kind=spec.kind.value,
                    status=RecognitionStatus.UNKNOWN.value,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    error=str(exc),
                )
            )
            continue
        duration_ms = (time.perf_counter() - started) * 1000.0
        if match is None:
            rows.append(
                RecognitionRow(
                    name=name,
                    kind=spec.kind.value,
                    status=RecognitionStatus.MISS.value,
                    threshold=_spec_threshold(spec),
                    duration_ms=duration_ms,
                )
            )
            continue
        rows.append(
            RecognitionRow(
                name=name,
                kind=spec.kind.value,
                status=getattr(match.status, "value", str(match.status)),
                score=float(match.score),
                threshold=match.threshold,
                rect=match.rect,
                text=match.text,
                duration_ms=duration_ms,
            )
        )
    return rows


def _spec_threshold(spec: Recognition) -> float | None:
    if spec.kind is Kind.TEMPLATE:
        return spec.threshold
    if spec.kind is Kind.POINT:
        return 1.0
    return None


def _template_from_image(image: np.ndarray) -> Template:
    bgr = image
    if bgr.ndim == 2:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
    if bgr.shape[2] == 4:
        bgr = cv2.cvtColor(bgr, cv2.COLOR_BGRA2BGR)
    return Template(name="draft", image=np.ascontiguousarray(bgr))


def _label_outcome(
    label: str | None, matched: bool
) -> str:
    if label == "hit":
        return "true_positive" if matched else "false_negative"
    if label == "miss":
        return "false_positive" if matched else "true_negative"
    if label == "known_defect":
        return "known_defect_hit" if matched else "known_defect_miss"
    return "unlabeled_hit" if matched else "unlabeled_miss"


def evaluate_draft(
    fixture_manifest: dict[str, Any],
    template_image: np.ndarray,
    thresholds: Iterable[float],
    grayscale: bool = True,
    roi: Rect | None = None,
    name: str = "draft",
    frame_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    from ..image import load_image

    base = Path(fixture_manifest["_dir"])
    size = fixture_manifest.get("canonical_size", [1920, 1080])
    canonical = (int(size[0]), int(size[1]))
    allowed = set(frame_ids) if frame_ids is not None else None
    frames = []
    for entry in fixture_manifest["frames"]:
        if allowed is not None and str(entry["id"]) not in allowed:
            continue
        image = load_image(base / str(entry["file"]))
        screen = normalize_frame(image, canonical)
        frames.append((str(entry["id"]), screen, dict(entry.get("labels") or {})))
    template = _template_from_image(template_image)
    results: list[dict[str, Any]] = []
    for threshold in thresholds:
        spec = Recognition(
            name=name,
            kind=Kind.TEMPLATE,
            file="draft.png",
            threshold=float(threshold),
            grayscale=bool(grayscale),
            scales=(1.0,),
            roi=roi,
        )
        counts: dict[str, int] = {}
        details: list[dict[str, Any]] = []
        for frame_id, screen, labels in frames:
            try:
                matches = find_template(screen, template, spec, limit=1)
            except Exception as exc:
                details.append({"frame_id": frame_id, "error": str(exc)})
                counts["error"] = counts.get("error", 0) + 1
                continue
            matched = bool(matches)
            outcome = _label_outcome(labels.get(name), matched)
            counts[outcome] = counts.get(outcome, 0) + 1
            details.append(
                {
                    "frame_id": frame_id,
                    "label": labels.get(name),
                    "matched": matched,
                    "outcome": outcome,
                    "score": None if not matches else round(float(matches[0].score), 4),
                    "rect": None if not matches else matches[0].rect.to_list(),
                }
            )
        results.append(
            {
                "threshold": round(float(threshold), 4),
                "counts": counts,
                "details": details,
            }
        )
    return {
        "name": name,
        "grayscale": bool(grayscale),
        "roi": None if roi is None else roi.to_list(),
        "frames": len(frames),
        "thresholds": results,
    }


def evaluate_asset(
    fixture_manifest: dict[str, Any],
    vision: Vision,
    name: str,
    thresholds: Iterable[float],
) -> dict[str, Any]:
    spec = vision.assets.recognition(name)
    from ..image import load_image

    base = Path(fixture_manifest["_dir"])
    size = fixture_manifest.get("canonical_size", [1920, 1080])
    canonical = (int(size[0]), int(size[1]))
    prepared = []
    for entry in fixture_manifest["frames"]:
        image = load_image(base / str(entry["file"]))
        screen = normalize_frame(image, canonical)
        prepared.append((str(entry["id"]), screen, dict(entry.get("labels") or {})))
    results = []
    for threshold in thresholds:
        candidate = replace(spec, threshold=float(threshold))
        counts: dict[str, int] = {}
        details = []
        for frame_id, screen, labels in prepared:
            try:
                match = vision.find(screen, candidate)
            except Exception as exc:
                details.append({"frame_id": frame_id, "error": str(exc)})
                counts["error"] = counts.get("error", 0) + 1
                continue
            outcome = _label_outcome(labels.get(name), match is not None)
            counts[outcome] = counts.get(outcome, 0) + 1
            details.append(
                {
                    "frame_id": frame_id,
                    "label": labels.get(name),
                    "matched": match is not None,
                    "outcome": outcome,
                    "score": None if match is None else round(float(match.score), 4),
                }
            )
        results.append(
            {"threshold": round(float(threshold), 4), "counts": counts, "details": details}
        )
    return {
        "name": name,
        "kind": spec.kind.value,
        "roi": None if spec.roi is None else spec.roi.to_list(),
        "frames": len(prepared),
        "thresholds": results,
    }


def export_draft(
    draft_dir: str | Path,
    name: str,
    template_image: np.ndarray,
    threshold: float,
    grayscale: bool = True,
    source_note: str = "",
    roi: Rect | None = None,
) -> dict[str, str]:
    target = Path(draft_dir)
    templates = target / "templates"
    templates.mkdir(parents=True, exist_ok=True)
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in name) or "draft"
    template_path = templates / f"{safe}.png"
    save_image(template_path, template_image)
    entry: dict[str, Any] = {
        "file": template_path.name,
        "threshold": round(float(threshold), 3),
    }
    if not grayscale:
        entry["grayscale"] = False
    if roi is not None:
        entry["roi"] = roi.to_list()
    fragment_path = target / f"{safe}.yaml"
    fragment_path.write_text(
        yaml.safe_dump(
            {"assets": {safe: entry}}, allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    note_path = target / "README.md"
    note = (
        "# 草稿资源\n\n"
        f"- 识别项: `{safe}`\n"
        f"- 阈值: {round(float(threshold), 3)}\n"
        f"- 灰度: {bool(grayscale)}\n"
        f"- 来源: {source_note or 'Vision Studio'}\n\n"
        "确认无误后把模板复制到正式 `assets/templates`，再把 yaml 片段合并进 `assets/assets.yaml`。\n"
    )
    note_path.write_text(note, encoding="utf-8")
    return {
        "template": str(template_path),
        "fragment": str(fragment_path),
        "readme": str(note_path),
    }
