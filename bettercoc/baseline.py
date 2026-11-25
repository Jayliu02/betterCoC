from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import cv2
import numpy as np

from .config import Config
from .digits import DigitReader
from .errors import BetterCoCError
from .geometry import Rect
from .image import load_image, normalize_frame
from .template import Template, find_template
from .vision import Vision

FIXTURE_VERSION = 1
DEFAULT_FIXTURE_DIR = Path("tests/fixtures/baseline")
DEFAULT_OUTPUT = Path("runtime/diagnostics/baseline.json")
LABEL_HIT = "hit"
LABEL_MISS = "miss"
LABEL_KNOWN_DEFECT = "known_defect"
LABELS = (LABEL_HIT, LABEL_MISS, LABEL_KNOWN_DEFECT)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_paths(paths: Iterable[Path]) -> tuple[int, str]:
    digest = hashlib.sha256()
    items = sorted(paths)
    for path in items:
        digest.update(path.name.encode("utf-8"))
        digest.update(sha256_file(path).encode("ascii"))
    return len(items), digest.hexdigest()


def _git(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def collect_git_state(root: Path) -> dict[str, Any]:
    status = _git(root, ["status", "--porcelain"])
    lines = [line for line in status.splitlines() if line.strip()]
    return {
        "commit": _git(root, ["rev-parse", "HEAD"]) or None,
        "branch": _git(root, ["rev-parse", "--abbrev-ref", "HEAD"]) or None,
        "dirty": bool(lines),
        "changed_files": len(lines),
        "untracked_files": sum(1 for line in lines if line.startswith("??")),
    }


def collect_packages() -> dict[str, Any]:
    import yaml

    try:
        from PIL import __version__ as pillow_version
    except Exception:
        pillow_version = None
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "pyyaml": getattr(yaml, "__version__", None),
        "pillow": pillow_version,
    }


def collect_assets_state(config: Config | None, assets_manifest: Path) -> dict[str, Any]:
    manifest = Path(assets_manifest).resolve()
    root = manifest.parent
    data = {}
    if manifest.exists():
        import yaml

        loaded = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        entries = loaded.get("assets") or {}
        data["entries"] = len(entries)
        data["template_root"] = str(root / str(loaded.get("template_root", "templates")))
    else:
        data["entries"] = 0
        data["template_root"] = None
    template_root = Path(data["template_root"]) if data["template_root"] else root / "templates"
    count, digest = sha256_paths(template_root.glob("*.png")) if template_root.exists() else (0, "")
    data["manifest"] = str(manifest)
    data["manifest_sha256"] = sha256_file(manifest) if manifest.exists() else None
    data["template_count"] = count
    data["templates_sha256"] = digest or None
    digits = root / "digits"
    if config is not None:
        try:
            digits = config.resolve_path(config.get("vision.digits", str(root / "digits")))
        except BetterCoCError:
            pass
    digit_files = sorted(digits.glob("*.png")) if digits.exists() else []
    digit_count, digit_digest = sha256_paths(digit_files)
    data["digits_dir"] = str(digits)
    data["digits_count"] = digit_count
    data["digits_sha256"] = digit_digest or None
    return data


def collect_environment(
    root: Path | None = None,
    config: Config | None = None,
    assets_manifest: Path | None = None,
    canonical: tuple[int, int] = (1920, 1080),
) -> dict[str, Any]:
    base = Path(root) if root else repo_root()
    manifest = Path(assets_manifest) if assets_manifest else base / "assets" / "assets.yaml"
    environment: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cwd": str(Path.cwd()),
        "repo_root": str(base),
        "canonical_size": [int(canonical[0]), int(canonical[1])],
        "packages": collect_packages(),
        "git": collect_git_state(base),
        "assets": collect_assets_state(config, manifest),
    }
    if config is not None and config.path is not None:
        environment["config"] = {
            "path": str(config.path),
            "sha256": sha256_file(config.path),
        }
        try:
            device = {
                "adb_path": config.get("device.adb_path", "adb"),
                "serial": config.get("device.serial", None),
                "capture_backend": config.get("capture.backend", "adb"),
                "control_backend": config.get("control.backend", "adb"),
                "dry_run": bool(config.get("runtime.dry_run", False)),
            }
        except BetterCoCError:
            device = {}
        environment["device_config"] = device
    return environment


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(ordered[int(position)])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


def measure(
    name: str,
    func: Callable[[], Any],
    iterations: int = 100,
    warmup: int = 3,
    note: str = "",
) -> dict[str, Any]:
    samples: list[float] = []
    errors = 0
    last_error: str | None = None
    for _ in range(max(0, warmup)):
        try:
            func()
        except Exception as exc:
            errors += 1
            last_error = f"{type(exc).__name__}: {exc}"
    for _ in range(max(1, iterations)):
        started = time.perf_counter()
        try:
            func()
        except Exception as exc:
            errors += 1
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        samples.append((time.perf_counter() - started) * 1000.0)
    return {
        "name": name,
        "iterations": max(1, iterations),
        "samples": len(samples),
        "errors": errors,
        "p50_ms": round(percentile(samples, 0.5), 3),
        "p95_ms": round(percentile(samples, 0.95), 3),
        "mean_ms": round(sum(samples) / len(samples), 3) if samples else 0.0,
        "min_ms": round(min(samples), 3) if samples else 0.0,
        "max_ms": round(max(samples), 3) if samples else 0.0,
        "note": note,
        "last_error": last_error,
    }


def load_fixture_manifest(fixture_dir: str | Path) -> dict[str, Any]:
    base = Path(fixture_dir)
    path = base / "manifest.json" if base.is_dir() else base
    if not path.exists():
        raise BetterCoCError(f"固定测试集清单不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("frames"), list):
        raise BetterCoCError(f"固定测试集清单格式错误: {path}")
    data["_path"] = str(path)
    data["_dir"] = str(path.parent)
    return data


def resolve_manifest_path(manifest: dict[str, Any], key: str) -> Path | None:
    value = manifest.get(key)
    if not value:
        return None
    return (Path(manifest["_dir"]) / str(value)).resolve()


def verify_fixtures(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    base = Path(manifest["_dir"])
    seen: set[str] = set()
    for frame in manifest["frames"]:
        frame_id = str(frame.get("id"))
        if frame_id in seen:
            issues.append(f"重复的帧 ID: {frame_id}")
        seen.add(frame_id)
        path = base / str(frame.get("file", ""))
        if not path.exists():
            issues.append(f"{frame_id}: 缺少文件 {path}")
            continue
        expected = (frame.get("stored") or {}).get("file_sha256")
        if expected and sha256_file(path) != expected:
            issues.append(f"{frame_id}: 文件哈希不一致 {path}")
        for name, label in (frame.get("labels") or {}).items():
            if label not in LABELS:
                issues.append(f"{frame_id}: 标签 {name}={label} 无效")
    return issues


def _frame_screen(path: Path, canonical: tuple[int, int]):
    return normalize_frame(load_image(path), canonical)


def run_fixture_set(
    manifest: dict[str, Any],
    vision: Vision,
    canonical: tuple[int, int] | None = None,
) -> dict[str, Any]:
    size = canonical or tuple(manifest.get("canonical_size", (1920, 1080)))
    canonical_size = (int(size[0]), int(size[1]))
    base = Path(manifest["_dir"])
    frames: list[dict[str, Any]] = []
    totals = {
        "frames": 0,
        "checks": 0,
        "passed": 0,
        "failed": 0,
        "known_defects": 0,
        "resolved": 0,
        "errors": 0,
    }
    for frame in manifest["frames"]:
        entry: dict[str, Any] = {
            "id": frame.get("id"),
            "state": frame.get("state"),
            "tags": list(frame.get("tags") or []),
            "checks": [],
        }
        path = base / str(frame.get("file", ""))
        started = time.perf_counter()
        try:
            screen = _frame_screen(path, canonical_size)
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
            totals["errors"] += 1
            frames.append(entry)
            continue
        entry["image"] = {"file": str(frame.get("file")), "width": screen.width, "height": screen.height}
        entry["viewport"] = {
            "device_width": screen.viewport.device_width,
            "device_height": screen.viewport.device_height,
        }
        for name, expected in sorted((frame.get("labels") or {}).items()):
            check: dict[str, Any] = {"asset": name, "expected": expected}
            sample_started = time.perf_counter()
            try:
                match = vision.find(screen, name)
            except Exception as exc:
                check.update(
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                )
                totals["errors"] += 1
                entry["checks"].append(check)
                continue
            check["actual"] = LABEL_HIT if match is not None else LABEL_MISS
            if match is not None:
                check["score"] = round(float(match.score), 4)
                check["rect"] = match.rect.to_list()
                check["text"] = match.text
            check["duration_ms"] = round(
                (time.perf_counter() - sample_started) * 1000.0, 3
            )
            if expected == LABEL_HIT:
                check["status"] = "pass" if match is not None else "fail"
            elif expected == LABEL_MISS:
                check["status"] = "pass" if match is None else "fail"
            else:
                check["status"] = "known_defect" if match is not None else "resolved"
            totals["checks"] += 1
            counter = {
                "pass": "passed",
                "fail": "failed",
                "known_defect": "known_defects",
                "resolved": "resolved",
            }.get(check["status"])
            if counter:
                totals[counter] += 1
            entry["checks"].append(check)
        entry["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        totals["frames"] += 1
        frames.append(entry)
    return {"summary": totals, "frames": frames}


def _fixture_frame(manifest: dict[str, Any], frame_id: str) -> dict[str, Any] | None:
    for frame in manifest["frames"]:
        if frame.get("id") == frame_id:
            return frame
    return None


def _find_labeled_frame(manifest: dict[str, Any], tags: Iterable[str]) -> dict[str, Any] | None:
    wanted = {tag for tag in tags}
    for frame in manifest["frames"]:
        if wanted & set(frame.get("tags") or []):
            return frame
    return None


def time_recognition_pipeline(
    manifest: dict[str, Any],
    vision: Vision,
    canonical: tuple[int, int],
    iterations: int = 100,
) -> list[dict[str, Any]]:
    base = Path(manifest["_dir"])
    home = _find_labeled_frame(manifest, ["home"]) or manifest["frames"][0]
    dialog = _find_labeled_frame(manifest, ["disconnect"]) or home
    home_screen = _frame_screen(base / str(home["file"]), canonical)
    dialog_screen = _frame_screen(base / str(dialog["file"]), canonical)
    ok, encoded = cv2.imencode(".png", home_screen.image)
    if not ok:
        raise BetterCoCError("基准帧 PNG 编码失败")
    png_bytes = encoded.tobytes()

    template_name = "game_stop"
    template_spec = vision.assets.recognition(template_name)
    template = vision.assets.template(template_spec)
    digit_reader = vision.digits or DigitReader(Path("assets/digits"))
    digit_roi = Rect(1580, 20, 240, 70)
    if vision.assets.has("home_gold"):
        digit_roi = vision.assets.recognition("home_gold").roi or digit_roi
    point_check = None
    if vision.assets.has("home_attack"):
        point_check = vision.assets.recognition("home_attack").check

    results = [
        measure(
            "decode_png",
            lambda: cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR),
            iterations=iterations,
            note="cv2.imdecode 1920x1080 PNG",
        ),
        measure(
            "normalize_frame",
            lambda: normalize_frame(home_screen.image.copy(), canonical),
            iterations=iterations,
            note="copy + 缩放到 canonical",
        ),
        measure(
            "template_match",
            lambda: find_template(
                dialog_screen,
                template,
                template_spec,
                limit=1,
            ),
            iterations=iterations,
            note=f"模板 {template_name} 全屏匹配",
        ),
        measure(
            "digits_read",
            lambda: digit_reader.read(home_screen, digit_roi),
            iterations=iterations,
            note=f"数字区域 {digit_roi}",
        ),
    ]
    if point_check is not None:
        results.append(
            measure(
                "point_color_check",
                lambda: Vision.point_check(home_screen, point_check),
                iterations=iterations,
                note="home_attack 颜色校验",
            )
        )
    results.append(
        measure(
            "fixture_load",
            lambda: load_image(base / str(home["file"])),
            iterations=iterations,
            note="从磁盘读取 webp 基准帧",
        )
    )
    return results


def time_adb_capture(
    config: Config,
    iterations: int = 100,
    canonical: tuple[int, int] = (1920, 1080),
) -> list[dict[str, Any]]:
    from .adb import AdbDevice

    device = AdbDevice(
        adb_path=str(config.get("device.adb_path", "adb")),
        serial=config.get("device.serial", None),
    )
    notes: dict[str, Any] = {}
    try:
        serial = device.resolve()
    except BetterCoCError as exc:
        return [
            {
                "name": "adb_capture",
                "iterations": 0,
                "samples": 0,
                "errors": 1,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "mean_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "note": "ADB 不可用，未测量",
                "last_error": str(exc),
            }
        ]
    payloads: list[bytes] = []

    def capture() -> int:
        payload = device._run(["exec-out", "screencap", "-p"]).stdout
        payloads.append(payload)
        if len(payloads) > 8:
            payloads.pop(0)
        return len(payload)

    transfer = measure(
        "adb_screencap_transfer",
        capture,
        iterations=iterations,
        warmup=1,
        note=f"adb exec-out screencap -p, serial={serial}",
    )
    if not payloads:
        return [transfer]
    last = payloads[-1]
    notes["payload_bytes"] = len(last)
    transfer["payload_bytes"] = len(last)
    decode = measure(
        "adb_png_decode",
        lambda: cv2.imdecode(np.frombuffer(last, dtype=np.uint8), cv2.IMREAD_COLOR),
        iterations=iterations,
        note="adb PNG 解码",
    )
    normalized = measure(
        "adb_normalize",
        lambda: normalize_frame(
            cv2.imdecode(np.frombuffer(last, dtype=np.uint8), cv2.IMREAD_COLOR),
            canonical,
        ),
        iterations=iterations,
        note="adb 帧解码后归一化",
    )
    pixel = cv2.imdecode(np.frombuffer(last, dtype=np.uint8), cv2.IMREAD_COLOR)
    if pixel is not None:
        transfer["frame_size"] = [int(pixel.shape[1]), int(pixel.shape[0])]
    return [transfer, decode, normalized]


def build_baseline(
    fixture_manifest: dict[str, Any],
    config: Config | None = None,
    vision: Vision | None = None,
    canonical: tuple[int, int] = (1920, 1080),
    iterations: int = 100,
    adb_iterations: int = 0,
    root: Path | None = None,
) -> dict[str, Any]:
    manifest_assets = resolve_manifest_path(fixture_manifest, "assets_manifest")
    if vision is None:
        raise BetterCoCError("build_baseline 需要 Vision 实例")
    environment = collect_environment(
        root=root,
        config=config,
        assets_manifest=manifest_assets,
        canonical=canonical,
    )
    environment["fixtures"] = fixture_manifest.get("_path")
    environment["fixture_version"] = fixture_manifest.get("version")
    fixtures = run_fixture_set(fixture_manifest, vision, canonical)
    timings = time_recognition_pipeline(
        fixture_manifest, vision, canonical, iterations=iterations
    )
    unverified = [
        "真实设备识别准确率（固定测试集来自历史 MuMu 截图，仅代表该账号与 UI）",
        "OCR 路径耗时（本机未安装 Tesseract）",
        "真实设备 dry-run（本机未连接设备时未执行）",
    ]
    if adb_iterations > 0 and config is not None:
        timings.extend(time_adb_capture(config, iterations=adb_iterations, canonical=canonical))
    else:
        timings.append(
            {
                "name": "adb_capture",
                "iterations": 0,
                "samples": 0,
                "errors": 0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "mean_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "note": "未测量：需要 --adb-iterations 且真实设备可用",
                "last_error": None,
            }
        )
    return {
        "schema_version": 1,
        "environment": environment,
        "fixtures": fixtures,
        "timings": timings,
        "unverified": unverified,
    }


def write_json_atomic(path: str | Path, data: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(target)
    return target


def build_vision_from_manifest(
    fixture_manifest: dict[str, Any], config: Config | None = None
) -> Vision:
    from .assets import AssetStore

    manifest_path = resolve_manifest_path(fixture_manifest, "assets_manifest")
    if manifest_path is None:
        raise BetterCoCError("固定测试集清单缺少 assets_manifest")
    digits_path = resolve_manifest_path(fixture_manifest, "digits_dir")
    if digits_path is None:
        digits_path = manifest_path.parent / "digits"
    assets = AssetStore(manifest_path)
    return Vision(assets, None, DigitReader(digits_path))


def format_summary(data: dict[str, Any]) -> str:
    environment = data.get("environment", {})
    fixtures = data.get("fixtures", {}).get("summary", {})
    lines = [
        "基线摘要",
        f"  时间: {environment.get('generated_at')}",
        f"  git: {environment.get('git', {}).get('commit')} "
        f"dirty={environment.get('git', {}).get('dirty')}",
        f"  Python: {environment.get('packages', {}).get('python')} "
        f"OpenCV {environment.get('packages', {}).get('opencv')} "
        f"numpy {environment.get('packages', {}).get('numpy')}",
        f"  固定测试集: {environment.get('fixtures')}",
        f"  验收: 帧 {fixtures.get('frames', 0)}，检查 {fixtures.get('checks', 0)}，"
        f"通过 {fixtures.get('passed', 0)}，失败 {fixtures.get('failed', 0)}，"
        f"已知缺陷 {fixtures.get('known_defects', 0)}，已修复 {fixtures.get('resolved', 0)}",
        "  耗时 P50/P95 (ms):",
    ]
    for timing in data.get("timings", []):
        if timing.get("samples"):
            lines.append(
                f"    {timing['name']:<24} n={timing['samples']:<4} "
                f"P50={timing['p50_ms']:<9} P95={timing['p95_ms']:<9} "
                f"错误={timing['errors']}"
            )
        else:
            lines.append(f"    {timing['name']:<24} 未测量（{timing.get('note')}）")
    failures = [
        (frame["id"], check)
        for frame in data.get("fixtures", {}).get("frames", [])
        for check in frame.get("checks", [])
        if check.get("status") == "fail"
    ]
    if failures:
        lines.append("  失败项:")
        for frame_id, check in failures:
            lines.append(
                f"    {frame_id}:{check['asset']} 期望 {check['expected']} "
                f"实际 {check.get('actual', check.get('status'))}"
            )
    return "\n".join(lines)
