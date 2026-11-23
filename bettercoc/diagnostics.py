from __future__ import annotations

from dataclasses import dataclass

from .adb import AdbDevice
from .assets import AssetStore
from .config import Config
from .digits import DigitReader
from .errors import BetterCoCError
from .image import load_image
from .ocr import TesseractOcr
from .template import build_mask


@dataclass
class Check:
    level: str
    message: str


def _assets_check(config: Config) -> list[Check]:
    checks: list[Check] = []
    manifest = config.resolve_path(config.get("vision.assets", "assets/assets.yaml"))
    if not manifest.exists():
        checks.append(Check("FAIL", f"资源清单不存在: {manifest}"))
        return checks
    try:
        store = AssetStore(manifest)
    except BetterCoCError as exc:
        checks.append(Check("FAIL", str(exc)))
        return checks
    checks.append(Check("OK", f"资源清单: {manifest} ({len(store.names())} 项)"))
    for issue in store.validate():
        checks.append(Check("FAIL", issue))
    missing = store.missing_files()
    for item in missing:
        checks.append(Check("WARN", f"待校准模板 {item}"))
    if missing:
        checks.append(
            Check(
                "WARN",
                f"还有 {len(missing)} 个备用模板未校准；自动战斗流程不依赖 scout_attack / battle_end。",
            )
        )
    for name in store.names():
        try:
            spec = store.recognition(name)
            if spec.kind.value == "template" and spec.file:
                path = store.template_root / spec.file
                if not path.exists():
                    continue
                image = load_image(path)
                bgr, _ = build_mask(
                    image, spec.use_alpha, spec.mask_color, spec.mask_tolerance
                )
                if spec.roi:
                    if spec.roi.width < bgr.shape[1] or spec.roi.height < bgr.shape[0]:
                        checks.append(
                            Check(
                                "FAIL",
                                f"{name} 的 ROI 小于模板，永远无法匹配: {spec.roi}",
                            )
                        )
        except Exception as exc:
            checks.append(Check("FAIL", f"{name}: {exc}"))
    digit_dir = config.resolve_path(config.get("vision.digits", "assets/digits"))
    reader = DigitReader(digit_dir)
    if reader.available():
        checks.append(
            Check("OK", f"数字模板: {digit_dir} ({sum(len(v) for v in reader.templates.values())} 个)")
        )
    else:
        checks.append(Check("WARN", f"数字模板不完整: {digit_dir}"))
    return checks


def run_doctor(config: Config) -> list[Check]:
    checks: list[Check] = []
    for issue in config.validate_core():
        checks.append(Check("FAIL", issue))
    checks.append(Check("OK", f"配置文件: {config.path or '内存配置'}"))
    checks.extend(_assets_check(config))
    capture_backend = config.get("capture.backend", "adb")
    control_backend = config.get("control.backend", "adb")
    if capture_backend == "adb" or control_backend == "adb":
        try:
            device = AdbDevice(
                adb_path=str(config.get("device.adb_path", "adb")),
                serial=config.get("device.serial", None),
            )
            serial = device.resolve()
            checks.append(Check("OK", f"ADB 设备: {serial}"))
        except BetterCoCError as exc:
            checks.append(Check("WARN", f"ADB 不可用: {exc}"))
    ocr_config = config.section("vision.ocr")
    backend = str(ocr_config.get("backend", "auto"))
    if backend != "none":
        ocr = TesseractOcr(
            lang=str(ocr_config.get("lang", "eng")),
            psm=int(ocr_config.get("psm", 6)),
            tesseract_cmd=ocr_config.get("tesseract_cmd"),
        )
        if ocr.available():
            checks.append(Check("OK", "OCR: Tesseract 可用"))
        else:
            checks.append(
                Check(
                    "WARN",
                    "OCR 不可用；文本识别项不可用，数字资源识别由 assets/digits 提供。",
                )
            )
    if config.get("task.name", "raid") == "raid":
        slots = config.get("task.raid.army.troop_slots", [])
        deploy = config.get("task.raid.army.deploy_points", [])
        if not slots or not deploy:
            checks.append(Check("WARN", "未配置兵种或下兵坐标；自动战斗不依赖手动下兵。"))
        if not config.get("task.raid.loot_check", False):
            checks.append(Check("WARN", "task.raid.loot_check 未开启，将不筛选对手资源。"))
    return checks
