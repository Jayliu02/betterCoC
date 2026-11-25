from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import MissingAssetError, StopRequested, TaskError
from .geometry import Rect
from .result import Match

if TYPE_CHECKING:
    from .context import Context

GAME_STOP = "game_stop"
HOME_ATTACK = "home_attack"
HOME_POPUP_CLOSE = "home_popup_close"
SIDE_PANEL_CLOSE = "side_panel_close"
BATTLE_RETURN = "battle_return_home"
EXIT_CANCEL = "exit_cancel"
SCOUT_CANCEL = "scout_cancel"
BATTLE_CONFIRM = "battle_confirm"
DEFAULT_TIMEOUT = 90.0
DEFAULT_PACKAGE = "com.tencent.tmgp.supercell.clashofclans"
DEFAULT_RESTART_TIMEOUT = 180.0
POLL_INTERVAL = 2.0
HOME_ATTEMPTS = 8
HOME_CLOSERS = (
    (SIDE_PANEL_CLOSE, 0.6),
    (HOME_POPUP_CLOSE, 0.6),
)
LOADING_ROI = Rect(700, 300, 500, 400)


def _is_loading(screen) -> bool:
    crop = getattr(screen, "crop", None)
    if crop is None:
        return False
    patch = crop(LOADING_ROI)
    if patch.size == 0:
        return False
    flat = patch.reshape(-1, 3).astype("float32")
    return float(flat.mean()) > 225 and float(flat.std()) < 30


def ensure_home(
    ctx: Context,
    attempts: int = HOME_ATTEMPTS,
    label: str = "主界面",
) -> None:
    if not ctx.vision.assets.has(HOME_ATTACK):
        raise MissingAssetError(
            f"缺少主界面识别项 {HOME_ATTACK}，在 assets.yaml 中补上固定坐标。"
        )
    last_screen = None
    for _ in range(max(1, attempts)):
        if ctx.should_stop():
            raise StopRequested("已请求停止")
        screen = ctx.screen()
        last_screen = screen
        if reload_if_stopped(ctx, screen=screen):
            continue
        handled = False
        for name, delay in HOME_CLOSERS:
            match = ctx.find_optional(name, screen=screen)
            if match is not None:
                ctx.logger.info("关闭 %s", name)
                ctx.tap_match(match)
                ctx.sleep(delay)
                handled = True
                break
        if handled:
            continue
        scout = ctx.find_optional(SCOUT_CANCEL, screen=screen)
        if scout is not None:
            confirm = ctx.find_optional(BATTLE_CONFIRM, screen=screen)
            target = confirm if confirm is not None else scout
            ctx.logger.info("结束当前侦察/战斗: %s", target.name)
            ctx.tap_match(target)
            ctx.sleep(1.2)
            continue
        cancel = ctx.find_optional(EXIT_CANCEL, screen=screen)
        if cancel is not None:
            ctx.logger.info("关闭退出游戏弹窗")
            ctx.tap_match(cancel)
            ctx.sleep(0.8)
            continue
        returned = ctx.find_optional(BATTLE_RETURN, screen=screen)
        if returned is not None:
            ctx.logger.info("点击回营")
            ctx.tap_match(returned)
            ctx.sleep(1.5)
            continue
        if ctx.find(HOME_ATTACK, screen=screen) is not None:
            return
        if _is_loading(screen):
            ctx.logger.info("画面切换中，等待")
            ctx.sleep(1.0)
            continue
        ctx.back()
        ctx.sleep(0.8)
    ctx.logger.error("连续 %d 次尝试仍未回到%s", attempts, label)
    try:
        ctx.save_screenshot("ensure-home-failed", screen=last_screen)
    except Exception:
        ctx.logger.exception("保存失败截图出错")
    raise TaskError(
        f"{attempts} 次尝试后仍未回到{label}，检查 assets.yaml 中 "
        f"{HOME_ATTACK} 的坐标与颜色校验"
    )


def reload_if_stopped(ctx: Context, screen=None) -> bool:
    if not ctx.vision.assets.has(GAME_STOP):
        return False
    match = ctx.find_optional(GAME_STOP, screen=screen)
    if match is None:
        return False
    _reload_game(ctx, match, screen)
    return True


def _reload_game(ctx: Context, match: Match, screen) -> None:
    timeout = float(ctx.config.get("runtime.reload_timeout", DEFAULT_TIMEOUT))
    ctx.stats.incr("game_reloads")
    ctx.logger.warning(
        "检测到断线重连弹窗，点击“重新载入游戏”，最多等待 %.0f 秒", timeout
    )
    try:
        ctx.save_screenshot("game-stopped", screen=screen)
    except Exception:
        ctx.logger.exception("保存断线截图失败")
    ctx.tap_match(match)
    deadline = ctx.clock() + timeout
    ctx.sleep(3.0)
    while ctx.clock() < deadline:
        if ctx.should_stop():
            raise StopRequested("重新载入游戏时收到停止请求")
        screen = ctx.screen()
        again = ctx.find_optional(GAME_STOP, screen=screen)
        if again is not None:
            ctx.logger.warning("断线弹窗仍在，再次点击“重新载入游戏”")
            ctx.tap_match(again)
            ctx.sleep(3.0)
            continue
        popup = ctx.find_optional(HOME_POPUP_CLOSE, screen=screen)
        if popup is not None:
            ctx.tap_match(popup)
            ctx.sleep(0.8)
            continue
        panel = ctx.find_optional(SIDE_PANEL_CLOSE, screen=screen)
        if panel is not None:
            ctx.tap_match(panel)
            ctx.sleep(0.8)
            continue
        returned = ctx.find_optional(BATTLE_RETURN, screen=screen)
        if returned is not None:
            ctx.tap_match(returned)
            ctx.sleep(1.5)
            continue
        if ctx.find_optional(HOME_ATTACK, screen=screen) is not None:
            ctx.logger.info("游戏重新载入完成，已回到主界面")
            return
        ctx.sleep(POLL_INTERVAL)
    raise TaskError(f"重新载入游戏后 {timeout:g}s 内未进入主界面")


def restart_game(ctx: Context) -> None:
    if ctx.dry_run:
        raise TaskError("dry-run 模式不会重启游戏")
    package = str(ctx.config.get("runtime.game_package", DEFAULT_PACKAGE)).strip()
    if not package:
        raise TaskError("runtime.game_package 未配置")
    timeout = float(
        ctx.config.get("runtime.restart_timeout", DEFAULT_RESTART_TIMEOUT)
    )
    force_stop = getattr(ctx.controller, "force_stop", None)
    start_app = getattr(ctx.controller, "start_app", None)
    if force_stop is None or start_app is None:
        raise TaskError("当前控制后端不支持重启游戏")
    ctx.stats.incr("game_restarts")
    ctx.logger.warning("强制退出并重新启动游戏: %s", package)
    try:
        ctx.save_screenshot("game-restart")
    except Exception:
        ctx.logger.exception("保存重启前截图失败")
    force_stop(package)
    ctx.sleep(2.0)
    start_app(package)
    deadline = ctx.clock() + timeout
    ctx.sleep(4.0)
    while ctx.clock() < deadline:
        if ctx.should_stop():
            raise StopRequested("重启游戏时收到停止请求")
        screen = ctx.screen()
        if reload_if_stopped(ctx, screen=screen):
            continue
        popup = ctx.find_optional(HOME_POPUP_CLOSE, screen=screen)
        if popup is not None:
            ctx.logger.info("关闭开屏弹窗")
            ctx.tap_match(popup)
            ctx.sleep(1.0)
            continue
        panel = ctx.find_optional(SIDE_PANEL_CLOSE, screen=screen)
        if panel is not None:
            ctx.tap_match(panel)
            ctx.sleep(0.8)
            continue
        if ctx.find_optional(HOME_ATTACK, screen=screen) is not None:
            ctx.logger.info("游戏重新启动完成，已回到主界面")
            return
        ctx.sleep(POLL_INTERVAL)
    raise TaskError(f"重启游戏后 {timeout:g}s 内未进入主界面")
