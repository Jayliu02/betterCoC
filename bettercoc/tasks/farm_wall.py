from __future__ import annotations

import time
from dataclasses import dataclass

from ..context import Context
from ..errors import BetterCoCError, MissingAssetError, StopRequested, TaskError
from ..ocr import parse_number
from ..state import read_state, update_state
from .. import console, resources
from .base import Task, TaskResult
from .raid import RaidTask
from .wall_upgrade import (
    BATTLE_RETURN,
    HOME_ATTACK,
    HOME_DARK,
    HOME_ELIXIR,
    HOME_GOLD,
    HOME_POPUP_CLOSE,
    SIDE_PANEL_CLOSE,
    WallUpgradeTask,
)


@dataclass
class FarmMemory:
    cycles: int = 0
    raids: int = 0
    wall_upgrades: int = 0
    walls_done: int = 0
    gold_spent: int = 0
    elixir_spent: int = 0
    fatal: bool = False


class FarmWallTask(Task):
    name = "farm_wall"

    def run(self, ctx: Context) -> TaskResult:
        self.ctx = ctx
        self._load_settings()
        resources.ensure_loaded(ctx)
        state = read_state(self.state_file)
        self.last_wall_remaining = None
        raw_remaining = state.get("wall_remaining")
        if raw_remaining is not None:
            try:
                self.last_wall_remaining = max(0, int(raw_remaining))
            except (TypeError, ValueError):
                self.last_wall_remaining = None
        self.memory = FarmMemory(
            walls_done=max(self.walls_done_config, int(state.get("walls_done", 0)))
        )
        if self.last_wall_remaining is not None:
            self.memory.walls_done = max(
                self.memory.walls_done,
                max(0, self.total_walls - self.last_wall_remaining),
            )
        console.set_walls(
            self.last_wall_remaining,
            self.memory.walls_done,
            self.total_walls,
            reason="任务开始",
        )
        status = "success"
        reason = ""
        try:
            self._preflight()
            self._loop()
            if ctx.should_stop():
                status = "stopped"
            if self.memory.fatal:
                status = "failed"
            reason = self._summary(status)
        except StopRequested as exc:
            status = "stopped"
            reason = self._summary("stopped")
            ctx.logger.info("任务停止: %s", exc)
        except BetterCoCError as exc:
            status = "failed"
            self.memory.fatal = True
            reason = self._summary("failed") + f": {exc}"
            ctx.logger.exception("farm_wall 失败")
        finally:
            self._save_state()
        ctx.stats.set("farm_cycles", self.memory.cycles)
        ctx.stats.set("raids", self.memory.raids)
        ctx.stats.set("wall_upgrades", self.memory.wall_upgrades)
        ctx.stats.set("gold_spent", self.memory.gold_spent)
        ctx.stats.set("elixir_spent", self.memory.elixir_spent)
        return TaskResult(
            task=self.name,
            status=status,
            reason=reason,
            counters=ctx.stats.to_dict(),
            elapsed=ctx.elapsed,
            transitions=[],
        )

    def _load_settings(self) -> None:
        cfg = self.ctx.config
        self.full_gold = int(cfg.get("task.farm_wall.full_gold", 10_000_000))
        self.full_elixir = int(cfg.get("task.farm_wall.full_elixir", 10_000_000))
        self.total_walls = int(cfg.get("task.farm_wall.total_walls", 300))
        self.walls_done_config = int(cfg.get("task.farm_wall.walls_done", 0))
        self.wall_batch = max(0, int(cfg.get("task.farm_wall.wall_batch", 0)))
        self.max_cycles = int(cfg.get("task.farm_wall.max_cycles", 0))
        self.max_runtime_min = float(cfg.get("task.farm_wall.max_runtime_min", 0))
        self.state_file = cfg.resolve_path(
            cfg.get("task.farm_wall.state_file", "runtime/resource-state.json")
        )
        self.max_resource = int(
            cfg.get("task.farm_wall.max_resource", 20_000_000)
        )
        self.preflight_cost = int(
            cfg.get("task.wall_upgrade.cost_per_wall", 600_000)
        )
        self._last_gold = 0
        self._last_elixir = 0
        self._last_dark = 0

    def _preflight(self) -> None:
        ctx = self.ctx
        if self.last_wall_remaining == 0:
            ctx.logger.info("预检: 当前没有可升级城墙，跳过")
            return
        gold, elixir, _ = resources.snapshot()
        if gold < self.preflight_cost and elixir < self.preflight_cost:
            ctx.logger.info(
                "预检: 金币 %s / 圣水 %s 均不足单段成本 %s，跳过",
                gold,
                elixir,
                self.preflight_cost,
            )
            return
        ctx.logger.info(
            "预检: 当前资源可升级城墙，先清空可用金币/圣水"
        )
        remaining = (
            self.last_wall_remaining
            if self.last_wall_remaining is not None
            else max(0, self.total_walls - self.memory.walls_done)
        )
        result = WallUpgradeTask(
            max_upgrades=remaining,
            batch_size=self.wall_batch,
            drain_all=True,
        ).run(ctx)
        upgraded = int(result.counters.get("wall_upgrades", 0))
        self.memory.wall_upgrades += upgraded
        self.memory.gold_spent += int(result.counters.get("gold_spent", 0))
        self.memory.elixir_spent += int(result.counters.get("elixir_spent", 0))
        remaining_raw = result.counters.get("wall_remaining")
        if remaining_raw is not None:
            initial = max(0, int(remaining_raw))
            final = max(0, initial - upgraded)
            self.last_wall_remaining = final
            self.memory.walls_done = max(0, self.total_walls - final)
        else:
            self.memory.walls_done += upgraded
            if self.last_wall_remaining is not None:
                self.last_wall_remaining = max(
                    0, self.last_wall_remaining - upgraded
                )
        console.set_walls(
            self.last_wall_remaining,
            self.memory.walls_done,
            self.total_walls,
            reason=f"预检升级 {upgraded} 段",
        )
        if upgraded <= 0:
            ctx.logger.warning("预检未产生升级，进入主流程")
        self._save_state()

    def _loop(self) -> None:
        ctx = self.ctx
        while True:
            if ctx.should_stop():
                raise StopRequested("已请求停止")
            if self.max_cycles > 0 and self.memory.cycles >= self.max_cycles:
                ctx.logger.info("达到调度循环上限 %d", self.max_cycles)
                return
            if ctx.runtime_exceeded(self.max_runtime_min):
                ctx.logger.info("达到最大运行时间 %.0f 分钟", self.max_runtime_min)
                return
            self._ensure_home()
            gold, elixir, dark = self._read_resources()
            pending = self.last_wall_remaining is None or self.last_wall_remaining > 0
            ctx.logger.info(
                "资源 金币 %s / 圣水 %s / 暗黑 %s，城墙剩余 %s，已升级 %s/%s",
                gold,
                elixir,
                dark,
                "未知" if self.last_wall_remaining is None else self.last_wall_remaining,
                self.memory.walls_done,
                self.total_walls,
            )
            if not pending:
                ctx.logger.info("当前没有可升级城墙，退出")
                return
            full_gold = self.full_gold
            full_elixir = self.full_elixir
            if resources.MAX_LOADED:
                if resources.GOLD_MAX > 0:
                    full_gold = resources.GOLD_MAX
                if resources.ELIXIR_MAX > 0:
                    full_elixir = resources.ELIXIR_MAX
            full = gold >= full_gold and elixir >= full_elixir
            if full:
                if self.last_wall_remaining is not None:
                    remaining_walls = max(0, self.last_wall_remaining)
                else:
                    remaining_walls = max(0, self.total_walls - self.memory.walls_done)
                if remaining_walls <= 0:
                    ctx.logger.info("当前没有可升级城墙，退出")
                    return
                result = WallUpgradeTask(
                    max_upgrades=remaining_walls,
                    batch_size=self.wall_batch,
                ).run(ctx)
                upgraded = int(result.counters.get("wall_upgrades", 0))
                remaining_raw = result.counters.get("wall_remaining")
                if remaining_raw is not None:
                    remaining_count = max(0, int(remaining_raw))
                    final_remaining = max(0, remaining_count - upgraded)
                    self.last_wall_remaining = final_remaining
                    self.memory.walls_done = max(
                        0, self.total_walls - final_remaining
                    )
                elif self.last_wall_remaining is not None:
                    self.last_wall_remaining = max(
                        0, self.last_wall_remaining - upgraded
                    )
                    self.memory.walls_done = max(
                        0, self.total_walls - self.last_wall_remaining
                    )
                else:
                    self.memory.walls_done += upgraded
                if upgraded <= 0:
                    if self.last_wall_remaining == 0:
                        ctx.logger.info("当前没有可升级城墙，退出")
                    else:
                        ctx.logger.warning("资源已满但无法继续升级城墙，退出")
                    return
                self.memory.wall_upgrades += upgraded
                self.memory.gold_spent += int(result.counters.get("gold_spent", 0))
                self.memory.elixir_spent += int(result.counters.get("elixir_spent", 0))
                console.set_walls(
                    self.last_wall_remaining,
                    self.memory.walls_done,
                    self.total_walls,
                    reason=f"升级城墙 {upgraded} 段",
                )
            else:
                result = RaidTask(max_cycles=1).run(ctx)
                raids = int(result.counters.get("raids", 0))
                if raids <= 0:
                    ctx.logger.warning("进攻未产生有效结果，退出")
                    return
                self.memory.raids += raids
                ctx.sleep(1.5)
                self._ensure_home()
                resources.refresh(ctx, reason="进攻结束")
                self._last_gold, self._last_elixir, self._last_dark = (
                    resources.snapshot()
                )
            self.memory.cycles += 1
            self._save_state()

    def _ensure_home(self) -> None:
        ctx = self.ctx
        for _ in range(8):
            screen = ctx.screen()
            side_close = ctx.find_optional(SIDE_PANEL_CLOSE, screen=screen)
            if side_close is not None:
                ctx.tap_match(side_close)
                ctx.sleep(0.6)
                continue
            popup_close = ctx.find_optional(HOME_POPUP_CLOSE, screen=screen)
            if popup_close is not None:
                ctx.tap_match(popup_close)
                ctx.sleep(0.6)
                continue
            returned = ctx.find_optional(BATTLE_RETURN, screen=screen)
            if returned is not None:
                ctx.tap_match(returned)
                ctx.sleep(1.5)
                continue
            if ctx.find(HOME_ATTACK, screen=screen) is not None:
                return
            ctx.back()
            ctx.sleep(0.6)
        raise TaskError("无法回到主界面")

    def _read_resources(self) -> tuple[int, int, int]:
        self._last_gold, self._last_elixir, self._last_dark = resources.snapshot()
        self._save_state()
        return self._last_gold, self._last_elixir, self._last_dark

    def _read_number(self, name: str, screen) -> int:
        ctx = self.ctx
        if not ctx.vision.assets.has(name):
            return 0
        try:
            match = ctx.find(name, screen=screen)
        except MissingAssetError:
            return 0
        value = parse_number(match.text if match else None)
        return value or 0

    def _save_state(self) -> None:
        try:
            update_state(
                self.state_file,
                farm_updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                gold=self._last_gold,
                elixir=self._last_elixir,
                dark=self._last_dark,
                walls_done=self.memory.walls_done,
                wall_remaining=self.last_wall_remaining,
                farm_cycles=self.memory.cycles,
                farm_raids=self.memory.raids,
                farm_wall_upgrades=self.memory.wall_upgrades,
                farm_gold_spent=self.memory.gold_spent,
                farm_elixir_spent=self.memory.elixir_spent,
            )
        except OSError:
            self.ctx.logger.exception("写入调度状态失败")

    def _summary(self, status: str) -> str:
        base = (
            f"{self.memory.cycles} 轮调度，进攻 {self.memory.raids} 次，"
            f"升级城墙 {self.memory.wall_upgrades} 段，"
            f"累计 {self.memory.walls_done}/{self.total_walls}"
        )
        if status == "stopped":
            return base + "，已停止"
        if status == "failed":
            return base + "，失败"
        return base
