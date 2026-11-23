from __future__ import annotations

import argparse
import signal
import sys
import time
import traceback
from pathlib import Path

import cv2
import numpy as np
import yaml

from . import __version__
from .annotate import annotate_matches
from .app import build_context, build_vision
from .assets import AssetStore
from .config import Config
from .demo import run_demo
from .diagnostics import run_doctor
from .errors import BetterCoCError, MissingAssetError
from .image import load_image, normalize_frame, save_image
from .logging_utils import setup_logging
from .tasks import create_task
DEFAULT_CONFIG = "config/config.yaml"


def _parse_rect(value: str):
    from .geometry import Rect

    try:
        return Rect.from_value(value)
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"矩形格式应为 x,y,w,h: {exc}") from exc


def _load_config(args) -> Config:
    return Config.load(args.config)


def _canonical(config: Config) -> tuple[int, int]:
    size = config.get("vision.canonical_size", [1920, 1080])
    return int(size[0]), int(size[1])


def cmd_doctor(args) -> int:
    config = _load_config(args)
    checks = run_doctor(config)
    failures = 0
    for check in checks:
        print(f"[{check.level:<4}] {check.message}")
        if check.level == "FAIL":
            failures += 1
    return 1 if failures else 0


def cmd_status(args) -> int:
    config = _load_config(args)
    state_path = config.resolve_path(
        config.get("task.farm_wall.state_file", "runtime/resource-state.json")
    )
    from .console import set_max, set_walls, update
    from .state import read_state

    state = read_state(state_path)
    set_max(
        int(state.get("gold_max", 0)),
        int(state.get("elixir_max", 0)),
        int(state.get("dark_max", 0)),
        redraw=False,
    )
    remaining = state.get("wall_remaining")
    walls_done = state.get("walls_done")
    set_walls(
        int(remaining) if remaining is not None else None,
        int(walls_done) if walls_done is not None else None,
        int(config.get("task.farm_wall.total_walls", 300)),
        redraw=False,
    )
    if args.live:
        logger = setup_logging(args.log_level)
        components = build_context(config, logger)
        ctx = components.context
        from .resources import ensure_loaded

        try:
            ensure_loaded(ctx, force=True)
        except BetterCoCError as exc:
            print(f"读取失败: {exc}")
            return 1
    else:
        gold = int(state.get("gold", 0))
        elixir = int(state.get("elixir", 0))
        dark = int(state.get("dark", 0))
        update(gold, elixir, dark, reason="状态查询", force=True)
    print(f"状态文件: {state_path}")
    return 0


def cmd_capture(args) -> int:
    config = _load_config(args)
    logger = setup_logging(args.log_level)
    components = build_context(config, logger)
    try:
        screen = components.context.screen()
        output = Path(args.output) if args.output else Path(
            config.resolve_path(
                config.get("runtime.screenshot_dir", "runtime/screenshots")
            )
        ) / time.strftime("capture-%Y%m%d-%H%M%S.png")
        save_image(output, screen.image)
        print(f"截图: {output}")
        print(f"画面: {screen.width}x{screen.height}")
        print(f"设备: {screen.viewport.device_width}x{screen.viewport.device_height}")
        if screen.viewport.scale_x != 1.0 or screen.viewport.scale_y != 1.0:
            print(
                f"归一化到 {screen.width}x{screen.height}，"
                f"缩放 {screen.viewport.scale_x:.3f}/{screen.viewport.scale_y:.3f}"
            )
        return 0
    finally:
        components.context.close()


def cmd_recognize(args) -> int:
    config = _load_config(args)
    logger = setup_logging(args.log_level)
    canonical = _canonical(config)
    components = None
    try:
        if args.image:
            screen = normalize_frame(load_image(args.image), canonical)
            vision = build_vision(config)
        else:
            components = build_context(config, logger)
            screen = components.context.screen()
            vision = components.vision
        all_matches = []
        for name in args.names:
            try:
                if args.all:
                    found = vision.find_all(screen, name, limit=args.limit)
                else:
                    match = vision.find(screen, name)
                    found = [match] if match else []
            except MissingAssetError as exc:
                print(f"[MISS] {name}: {exc}", file=sys.stderr)
                continue
            if not found:
                print(f"[MISS] {name}")
                continue
            for match in found:
                text = f" text={match.text}" if match.text else ""
                print(
                    f"[HIT ] {name} rect={match.rect} score={match.score:.3f}{text}"
                )
                all_matches.append(match)
        if args.save:
            canvas = annotate_matches(screen.image, all_matches)
            save_image(args.save, canvas)
            print(f"标注图: {Path(args.save).resolve()}")
        return 0 if all_matches else 2
    finally:
        if components is not None:
            components.context.close()


def cmd_probe(args) -> int:
    config = _load_config(args)
    logger = setup_logging(args.log_level)
    canonical = _canonical(config)
    components = None
    try:
        if args.image:
            screen = normalize_frame(load_image(args.image), canonical)
            vision = build_vision(config)
        else:
            components = build_context(config, logger)
            screen = components.context.screen()
            vision = components.vision
        print(f"画面: {screen.width}x{screen.height}")
        all_matches = []
        for name in vision.assets.names():
            try:
                matches = vision.find_all(screen, name, limit=args.limit)
            except MissingAssetError as exc:
                print(f"[SKIP] {name}: {exc}")
                continue
            except Exception as exc:
                print(f"[FAIL] {name}: {exc}")
                continue
            if not matches:
                print(f"[MISS] {name}")
                continue
            for match in matches:
                text = f" text={match.text}" if match.text else ""
                print(
                    f"[HIT ] {name} rect={match.rect} score={match.score:.3f}{text}"
                )
                all_matches.append(match)
        if args.save:
            save_image(args.save, annotate_matches(screen.image, all_matches))
            print(f"标注图: {Path(args.save).resolve()}")
        return 0
    finally:
        if components is not None:
            components.context.close()


def cmd_sample(args) -> int:
    config = _load_config(args)
    logger = setup_logging(args.log_level)
    canonical = _canonical(config)
    components = None
    try:
        if args.image:
            screen = normalize_frame(load_image(args.image), canonical)
        else:
            components = build_context(config, logger)
            screen = components.context.screen()
        rect = args.rect.clamp(screen.width, screen.height)
        region = screen.crop(rect)
        if region.size == 0:
            print("采样区域为空", file=sys.stderr)
            return 1
        mean_bgr = region.reshape(-1, 3).mean(axis=0)
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV).reshape(-1, 3)
        median_hsv = np.median(hsv, axis=0)
        lower = [
            max(0, int(median_hsv[0]) - 15),
            max(0, int(median_hsv[1]) - 50),
            max(0, int(median_hsv[2]) - 50),
        ]
        upper = [
            min(179, int(median_hsv[0]) + 15),
            min(255, int(median_hsv[1]) + 50),
            min(255, int(median_hsv[2]) + 50),
        ]
        print(f"区域: {rect}")
        print(f"BGR 均值: ({mean_bgr[0]:.1f}, {mean_bgr[1]:.1f}, {mean_bgr[2]:.1f})")
        print(
            f"HSV 中位数: ({median_hsv[0]:.1f}, {median_hsv[1]:.1f}, {median_hsv[2]:.1f})"
        )
        print(f"建议 lower: [{lower[0]}, {lower[1]}, {lower[2]}]")
        print(f"建议 upper: [{upper[0]}, {upper[1]}, {upper[2]}]")
        return 0
    finally:
        if components is not None:
            components.context.close()


def _update_manifest(
    store: AssetStore,
    name: str,
    file_name: str,
    threshold: float,
    grayscale: bool,
) -> dict:
    data = yaml.safe_load(store.manifest_path.read_text(encoding="utf-8")) or {}
    assets = data.setdefault("assets", {})
    entry = {"file": file_name, "threshold": round(threshold, 3)}
    if not grayscale:
        entry["grayscale"] = False
    assets[name] = entry
    store.manifest_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return entry


def cmd_assets_add(args) -> int:
    config = _load_config(args)
    logger = setup_logging(args.log_level)
    if not args.name.replace("-", "").replace("_", "").isalnum():
        print("名称只能包含字母、数字、下划线和连字符", file=sys.stderr)
        return 1
    canonical = _canonical(config)
    store = AssetStore(config.resolve_path(config.get("vision.assets", "assets/assets.yaml")))
    components = None
    try:
        if args.image:
            screen = normalize_frame(load_image(args.image), canonical)
        else:
            components = build_context(config, logger)
            screen = components.context.screen()
        rect = args.rect.clamp(screen.width, screen.height)
        if rect.width < 8 or rect.height < 8:
            print("裁剪区域太小", file=sys.stderr)
            return 1
        template_path = store.template_root / f"{args.name}.png"
        if template_path.exists() and not args.force:
            print(f"模板已存在: {template_path}，加 --force 覆盖", file=sys.stderr)
            return 1
        save_image(template_path, screen.crop(rect))
        entry = _update_manifest(
            store,
            args.name,
            template_path.name,
            args.threshold,
            not args.color,
        )
        print(f"已写入模板: {template_path}")
        print(f"ROI 参考: [{rect.x}, {rect.y}, {rect.width}, {rect.height}]")
        print("清单条目:")
        print(yaml.safe_dump({args.name: entry}, allow_unicode=True, sort_keys=False).rstrip())
        print("提示: 若模板可能误匹配，把上面的 ROI 加到清单条目里。")
        return 0
    finally:
        if components is not None:
            components.context.close()


def cmd_assets_list(args) -> int:
    config = _load_config(args)
    store = AssetStore(config.resolve_path(config.get("vision.assets", "assets/assets.yaml")))
    for name in store.names():
        spec = store.recognition(name)
        if spec.kind.value == "template":
            target = str(spec.file)
            detail = f"threshold={spec.threshold}"
        elif spec.kind.value == "color":
            target = f"{spec.space} {spec.lower}..{spec.upper}"
            detail = f"min_ratio={spec.min_ratio}"
        elif spec.kind.value == "digits":
            target = str(spec.roi or "-")
            detail = "digits"
        else:
            target = str(spec.roi or "-")
            detail = f"regex={spec.regex or '-'}"
        print(
            f"{name:<24} {spec.kind.value:<9} {target:<32} "
            f"roi={spec.roi or '-'} {detail}"
        )
    return 0


def cmd_assets_check(args) -> int:
    config = _load_config(args)
    store = AssetStore(config.resolve_path(config.get("vision.assets", "assets/assets.yaml")))
    issues = store.validate()
    missing = store.missing_files()
    for issue in issues:
        print(f"[FAIL] {issue}")
    for item in missing:
        print(f"[WARN] 待校准 {item}")
    print(
        f"共 {len(store.names())} 项，缺失模板 {len(missing)} 个，格式问题 {len(issues)} 个"
    )
    return 1 if issues else 0


def cmd_run(args) -> int:
    config = _load_config(args)
    if args.max_cycles is not None:
        raid = config.data.setdefault("task", {}).setdefault("raid", {})
        raid["max_cycles"] = args.max_cycles
    if args.dry_run:
        config.data.setdefault("runtime", {})["dry_run"] = True
    logger = setup_logging(
        args.log_level,
        config.resolve_path(config.get("runtime.log_dir", "runtime/logs")),
    )
    components = build_context(config, logger, image_path=args.image)
    ctx = components.context
    task_name = args.task or config.get("task.name", "raid")
    task = create_task(task_name)
    from .resources import ensure_loaded

    try:
        ensure_loaded(ctx)
    except Exception:
        logger.exception("首次加载全局资源失败，任务内会再次尝试")
    previous_handler = signal.getsignal(signal.SIGINT)
    interrupt_count = [0]

    def handle_interrupt(signum, frame):
        interrupt_count[0] += 1
        if interrupt_count[0] == 1:
            logger.warning("收到 Ctrl+C，正在安全停止，再按一次强制退出")
            ctx.request_stop("收到 Ctrl+C")
        else:
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handle_interrupt)
    try:
        result = task.run(ctx)
        print("")
        print(f"任务: {result.task}")
        print(f"状态: {result.status}")
        print(f"结果: {result.reason}")
        print(f"耗时: {result.elapsed:.1f}s")
        print("计数: " + ", ".join(f"{key}={value}" for key, value in result.counters.items()))
        if args.trace:
            for item in result.transitions:
                print(f"  {item['from']} -> {item['to']} ({item['elapsed']:.2f}s)")
        if result.status == "failed":
            return 1
        if result.status == "stopped":
            return 2
        return 0
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        ctx.close()


def cmd_demo(args) -> int:
    result = run_demo(args.output, args.cycles)
    print("")
    print(f"演示状态: {result.result.status}")
    print(f"演示结果: {result.result.reason}")
    print(
        f"模拟器数据: 进攻 {result.game.raids} 次，"
        f"剩余金币 {result.game.gold:,}，圣水 {result.game.elixir:,}"
    )
    print(f"输出目录: {result.root}")
    return 0 if result.result.status == "success" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bettercoc",
        description="betterCoC - 基于图像识别的部落冲突自动化框架",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="配置文件路径")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    parser.add_argument("--version", action="version", version=f"bettercoc {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="检查配置、资源、ADB 与 OCR")
    doctor.set_defaults(func=cmd_doctor)

    status = subparsers.add_parser("status", help="显示当前全局资源和城墙数量")
    status.add_argument("--live", action="store_true", help="实时读取游戏主城资源")
    status.set_defaults(func=cmd_status)

    capture = subparsers.add_parser("capture", help="保存当前游戏画面")
    capture.add_argument("--output", "-o", default=None, help="输出图片路径")
    capture.set_defaults(func=cmd_capture)

    recognize = subparsers.add_parser("recognize", help="在截图或实时画面上执行识别")
    recognize.add_argument("names", nargs="+", help="资源清单中的识别项名称")
    recognize.add_argument("--image", default=None, help="使用图片代替实时截图")
    recognize.add_argument("--all", action="store_true", help="返回所有匹配")
    recognize.add_argument("--limit", type=int, default=10, help="最大匹配数")
    recognize.add_argument("--save", default=None, help="保存标注图")
    recognize.set_defaults(func=cmd_recognize)

    probe = subparsers.add_parser("probe", help="逐项检查全部识别项")
    probe.add_argument("--image", default=None, help="使用图片代替实时截图")
    probe.add_argument("--limit", type=int, default=5, help="每项最大匹配数")
    probe.add_argument("--save", default=None, help="保存标注图")
    probe.set_defaults(func=cmd_probe)

    sample = subparsers.add_parser("sample", help="采样区域颜色，辅助颜色识别校准")
    sample.add_argument("--rect", required=True, type=_parse_rect, help="x,y,w,h")
    sample.add_argument("--image", default=None, help="使用图片代替实时截图")
    sample.set_defaults(func=cmd_sample)

    assets = subparsers.add_parser("assets", help="资源清单工具")
    asset_sub = assets.add_subparsers(dest="asset_command", required=True)

    add = asset_sub.add_parser("add", help="从截图裁剪并加入模板清单")
    add.add_argument("--name", required=True, help="识别项名称")
    add.add_argument("--rect", required=True, type=_parse_rect, help="x,y,w,h")
    add.add_argument("--image", default=None, help="使用图片代替实时截图")
    add.add_argument("--threshold", type=float, default=0.86)
    add.add_argument("--color", action="store_true", help="使用三通道匹配")
    add.add_argument("--force", action="store_true", help="覆盖已有模板")
    add.set_defaults(func=cmd_assets_add)

    asset_list = asset_sub.add_parser("list", help="列出识别项")
    asset_list.set_defaults(func=cmd_assets_list)

    asset_check = asset_sub.add_parser("check", help="检查清单与模板文件")
    asset_check.set_defaults(func=cmd_assets_check)

    run = subparsers.add_parser("run", help="运行任务")
    run.add_argument("--task", default=None, help="任务名，默认读取 task.name")
    run.add_argument("--image", default=None, help="用静态图片调试识别流程")
    run.add_argument("--dry-run", action="store_true", help="只识别和打印点击，不操作设备")
    run.add_argument("--max-cycles", type=int, default=None, help="覆盖最大循环轮数")
    run.add_argument("--trace", action="store_true", help="打印状态转移")
    run.set_defaults(func=cmd_run)

    demo = subparsers.add_parser("demo", help="运行内置模拟器演示完整循环")
    demo.add_argument("--cycles", type=int, default=3, help="演示循环轮数")
    demo.add_argument("--output", default="runtime/demo", help="输出目录")
    demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130
    except BetterCoCError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        if args.log_level == "DEBUG":
            traceback.print_exc()
        return 1
    except Exception as exc:
        print(f"未处理错误: {type(exc).__name__}: {exc}", file=sys.stderr)
        if args.log_level == "DEBUG":
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
