from __future__ import annotations

from dataclasses import dataclass

from .adb import AdbDevice
from .assets import AssetStore
from .capture import Capture, create_capture
from .config import Config
from .context import Context
from .control import AdbController, Controller, NullController
from .digits import DigitReader
from .log import get_logger
from .ocr import create_ocr
from .vision import Vision


@dataclass
class Components:
    config: Config
    assets: AssetStore
    vision: Vision
    capture: Capture
    controller: Controller
    context: Context


def build_assets(config: Config) -> AssetStore:
    manifest = config.resolve_path(config.get("vision.assets", "assets/assets.yaml"))
    return AssetStore(manifest)


def build_vision(config: Config) -> Vision:
    assets = build_assets(config)
    ocr_config = config.section("vision.ocr")
    ocr = create_ocr(
        backend=str(ocr_config.get("backend", "auto")),
        lang=str(ocr_config.get("lang", "eng")),
        psm=int(ocr_config.get("psm", 6)),
        tesseract_cmd=ocr_config.get("tesseract_cmd"),
    )
    digit_dir = config.resolve_path(config.get("vision.digits", "assets/digits"))
    return Vision(assets, ocr, DigitReader(digit_dir))


def build_context(
    config: Config,
    logger=None,
    image_path: str | None = None,
    dry_run: bool | None = None,
) -> Components:
    logger = logger or get_logger()
    assets = build_assets(config)
    vision = build_vision(config)
    capture_backend = str(config.get("capture.backend", "adb"))
    control_backend = str(config.get("control.backend", "adb"))
    needs_adb = capture_backend == "adb" or (
        control_backend == "adb" and image_path is None
    )
    device = None
    if needs_adb:
        device = AdbDevice(
            adb_path=str(config.get("device.adb_path", "adb")),
            serial=config.get("device.serial", None),
        )
    capture = create_capture(
        backend=capture_backend,
        device=device,
        folder=config.get("capture.folder", None),
        loop=bool(config.get("capture.loop", True)),
        image_path=image_path,
    )
    if control_backend == "adb" and image_path is None:
        if device is None:
            raise ValueError("control.backend=adb 需要设备连接")
        controller: Controller = AdbController(device)
    else:
        controller = NullController()
    canonical = config.get("vision.canonical_size", [1920, 1080])
    jitter = int(config.get("control.tap_jitter", 2))
    delay = config.get("control.delay_ms", [120, 280])
    delay_seconds = (float(delay[0]) / 1000.0, float(delay[1]) / 1000.0)
    if dry_run is None:
        dry_run = bool(config.get("runtime.dry_run", False))
    context = Context(
        config=config,
        vision=vision,
        capture=capture,
        controller=controller,
        logger=logger,
        canonical=(int(canonical[0]), int(canonical[1])),
        dry_run=dry_run,
        jitter=jitter,
        tap_delay=delay_seconds,
    )
    return Components(
        config=config,
        assets=assets,
        vision=vision,
        capture=capture,
        controller=controller,
        context=context,
    )
