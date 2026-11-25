from __future__ import annotations

import time
from typing import TYPE_CHECKING

from . import console
from .errors import MissingAssetError
from .geometry import Rect
from .ocr import parse_number
from .recovery import ensure_home
from .state import read_state, update_state

if TYPE_CHECKING:
    from .context import Context

GOLD = 0
ELIXIR = 0
DARK = 0
GOLD_MAX = 0
ELIXIR_MAX = 0
DARK_MAX = 0
LOADED = False
MAX_LOADED = False
MAX_RESOURCE = 20_000_000
STATE_FILE = "runtime/resource-state.json"

HOME_GOLD = "home_gold"
HOME_ELIXIR = "home_elixir"
HOME_DARK = "home_dark"


def snapshot() -> tuple[int, int, int]:
    return GOLD, ELIXIR, DARK


def max_snapshot() -> tuple[int, int, int]:
    return GOLD_MAX, ELIXIR_MAX, DARK_MAX


def set_resources(gold: int, elixir: int, dark: int, reason: str = "") -> None:
    global GOLD, ELIXIR, DARK, LOADED
    GOLD = int(gold)
    ELIXIR = int(elixir)
    DARK = int(dark)
    LOADED = True
    console.update(GOLD, ELIXIR, DARK, reason=reason)


def adjust(
    gold: int = 0,
    elixir: int = 0,
    dark: int = 0,
    reason: str = "",
) -> tuple[int, int, int]:
    global GOLD, ELIXIR, DARK
    GOLD = max(0, GOLD + int(gold))
    ELIXIR = max(0, ELIXIR + int(elixir))
    DARK = max(0, DARK + int(dark))
    console.update(GOLD, ELIXIR, DARK, reason=reason)
    return GOLD, ELIXIR, DARK


def ensure_loaded(ctx: Context, force: bool = False) -> tuple[int, int, int]:
    if LOADED and not force:
        return snapshot()
    return refresh(ctx, reason="首次读取")


def refresh(ctx: Context, reason: str = "刷新") -> tuple[int, int, int]:
    global LOADED
    _ensure_home(ctx)
    _zoom_out_min(ctx)
    values = None
    for attempt in range(3):
        values = _read_resources(ctx)
        if values is not None:
            break
        ctx.logger.warning("资源读取失败，重试 %d/3", attempt + 1)
        ctx.sleep(0.8)
    if values is None:
        ctx.logger.error("无法读取主城资源，保留上一次全局值")
        return snapshot()
    gold, elixir, dark = values
    _seed_walls(ctx)
    if not MAX_LOADED:
        _read_max_values(ctx, (gold, elixir, dark))
        console.set_max(GOLD_MAX, ELIXIR_MAX, DARK_MAX, redraw=False)
    set_resources(gold, elixir, dark, reason=reason)
    ctx.logger.info(
        "全局资源已更新: 金币 %s，圣水 %s，暗黑 %s", gold, elixir, dark
    )
    _save_state(ctx)
    return snapshot()


def _read_resources(ctx: Context) -> tuple[int, int, int] | None:
    screen = ctx.screen()
    gold = _read_number(ctx, HOME_GOLD, screen)
    elixir = _read_number(ctx, HOME_ELIXIR, screen)
    dark = _read_number(ctx, HOME_DARK, screen)
    if gold is None or elixir is None or dark is None:
        return None
    if gold < 0 or elixir < 0 or dark < 0:
        return None
    if gold > MAX_RESOURCE or elixir > MAX_RESOURCE:
        return None
    return gold, elixir, dark


def _read_number(ctx: Context, name: str, screen) -> int | None:
    if not ctx.vision.assets.has(name):
        return None
    try:
        match = ctx.find(name, screen=screen)
    except MissingAssetError:
        return None
    if match is None:
        return None
    return parse_number(match.text)


def _ensure_home(ctx: Context) -> None:
    ensure_home(ctx, label="主城读取资源")


def _zoom_out_min(ctx: Context) -> None:
    if ctx.dry_run:
        ctx.logger.info("[dry-run] 跳过缩小主城视角")
        return
    pinch = getattr(ctx.controller, "pinch", None)
    if pinch is not None:
        ctx.logger.info("缩小主城视角到最小")
        pinch(540, 960, 260, 40, 12)
        ctx.sleep(0.5)
        return
    scroll = getattr(ctx.controller, "scroll", None)
    if scroll is None:
        return
    ctx.logger.info("缩小主城视角到最小")
    for _ in range(6):
        scroll(960, 540, -12)
        ctx.sleep(0.15)
    ctx.sleep(0.4)


def _seed_walls(ctx: Context) -> None:
    state = read_state(ctx.config.resolve_path(STATE_FILE))
    remaining = state.get("wall_remaining")
    done = state.get("walls_done")
    if remaining is None:
        return
    console.set_walls(
        int(remaining),
        int(done) if done is not None else None,
        int(ctx.config.get("task.farm_wall.total_walls", 300)),
        redraw=False,
    )


def _read_max_values(
    ctx: Context,
    current_values: tuple[int, int, int],
) -> None:
    global GOLD_MAX, ELIXIR_MAX, DARK_MAX, MAX_LOADED
    digits = ctx.vision.digits
    if digits is None:
        return
    checks = [
        ("gold", 1650, 60, (1590, 80, 230, 50), "gold_max", "full_gold", 10_000_000),
        (
            "elixir",
            1700,
            130,
            (1550, 155, 250, 50),
            "elixir_max",
            "full_elixir",
            10_000_000,
        ),
        ("dark", 1700, 200, (1700, 240, 200, 50), "dark_max", "full_dark", 200_000),
    ]
    values = {}
    current = {
        "gold": current_values[0],
        "elixir": current_values[1],
        "dark": current_values[2],
    }
    for label, x, y, roi, key, config_key, fallback in checks:
        value = None
        score = 0.0
        for _ in range(2):
            ctx.tap(x, y)
            ctx.sleep(0.55)
            screen = ctx.screen()
            label_match = ctx.find_optional("max_label", screen=screen)
            target = roi
            if label_match is not None:
                target = (
                    label_match.rect.right + 10,
                    label_match.rect.y - 5,
                    260,
                    50,
                )
            value, text, score = digits.read(
                screen,
                Rect(*target),
                max_height=48,
                max_width=40,
                white_threshold=245,
            )
            if value is not None and value > 0:
                break
            ctx.sleep(0.3)
        low = max(1, int(current[label] * 0.8))
        if value is not None and low <= value <= MAX_RESOURCE:
            values[key] = value
            ctx.logger.info("%s 上限 %s，识别分 %.2f", label, value, score)
        else:
            values[key] = int(ctx.config.get(f"task.farm_wall.{config_key}", fallback))
            ctx.logger.warning("%s 上限读取失败，使用配置 %s", label, values[key])
    _close_max_popup(ctx)
    GOLD_MAX = values["gold_max"]
    ELIXIR_MAX = values["elixir_max"]
    DARK_MAX = values["dark_max"]
    MAX_LOADED = True
    console.set_max(GOLD_MAX, ELIXIR_MAX, DARK_MAX, redraw=False)


def _close_max_popup(ctx: Context) -> None:
    for _ in range(3):
        if ctx.find_optional("max_label") is None:
            return
        ctx.tap(1700, 200)
        ctx.sleep(0.4)


def _save_state(ctx: Context) -> None:
    path = ctx.config.resolve_path(STATE_FILE)
    try:
        update_state(
            path,
            updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            gold=GOLD,
            elixir=ELIXIR,
            dark=DARK,
            gold_max=GOLD_MAX,
            elixir_max=ELIXIR_MAX,
            dark_max=DARK_MAX,
        )
    except OSError:
        ctx.logger.exception("写入全局资源状态失败")
