from __future__ import annotations

import time
from dataclasses import dataclass

from ..context import Context
from ..errors import BetterCoCError, StopRequested, TaskError
from ..recovery import ensure_home, restart_game
from ..state import update_state
from .. import console, resources
from .base import Task, TaskResult
from .raid import RaidTask
from .wall_upgrade import WallUpgradeTask


@dataclass
class FarmMemory:
    cycles: int = 0
    raids: int = 0
    wall_upgrades: int = 0
    gold_spent: int = 0
    elixir_spent: int = 0
    fatal: bool = False


class FarmWallTask(Task):
    name = "farm_wall"

    def run(self, ctx: Context) -> TaskResult:
        self.ctx = ctx
        self._begin(ctx)
        self._load_settings()
        resources.ensure_loaded(ctx)
        self.wall_remaining: int | None = None
        self.walls_complete = False
        self.memory = FarmMemory()
        console.set_walls(
            None,
            self.memory.wall_upgrades,
            complete=False,
            reason="任务开始",
        )
        status = "success"
        reason = ""
        try:
            self._schedule()
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
        ctx.stats.set(
            "wall_remaining", -1 if self.wall_remaining is None else self.wall_remaining
        )
        ctx.stats.set("wall_complete", 1 if self.walls_complete else 0)
        return TaskResult(
            task=self.name,
            status=status,
            reason=reason,
            counters=ctx.stats.to_dict(),
            elapsed=self._task_elapsed(ctx),
            transitions=[],
        )

    def _load_settings(self) -> None:
        cfg = self.ctx.config
        self.full_gold = int(cfg.get("task.farm_wall.full_gold", 10_000_000))
        self.full_elixir = int(cfg.get("task.farm_wall.full_elixir", 10_000_000))
        self.wall_batch = max(0, int(cfg.get("task.farm_wall.wall_batch", 0)))
        self.max_cycles = int(cfg.get("task.farm_wall.max_cycles", 0))
        self.max_runtime_min = float(cfg.get("task.farm_wall.max_runtime_min", 0))
        self.max_restarts = max(0, int(cfg.get("task.farm_wall.max_restarts", 5)))
        self.max_raid_retries = max(
            1, int(cfg.get("task.farm_wall.max_raid_retries", 3))
        )
        self.threshold_ratio = float(
            cfg.get("task.farm_wall.threshold_ratio", 0.9)
        )
        self.farm_after_complete = bool(
            cfg.get("task.farm_wall.farm_after_complete", False)
        )
        self.restarts = 0
        self.raid_failures = 0
        self.state_file = cfg.resolve_path(
            cfg.get("task.farm_wall.state_file", "runtime/resource-state.json")
        )
        self.max_resource = int(
            cfg.get("task.farm_wall.max_resource", 20_000_000)
        )
        self.wall_cost_gold = int(
            cfg.get("task.wall_upgrade.cost_per_wall", 600_000)
        )
        self.wall_cost_elixir = self.wall_cost_gold
        self._last_gold = 0
        self._last_elixir = 0
        self._last_dark = 0

    def _schedule(self) -> None:
        ctx = self.ctx
        gold, elixir, _ = self._read_resources()
        threshold = self._threshold()
        total = gold + elixir
        ctx.logger.info(
            "初始资源总和 %s，升墙阈值 %s（%.0f%%）",
            total,
            threshold,
            self.threshold_ratio * 100,
        )
        if self._walls_done():
            self._after_walls_complete()
            return
        if total > threshold:
            self._upgrade_walls()
            if self._walls_done():
                self._after_walls_complete()
                return
        while True:
            if self._limits_reached():
                return
            if self._walls_done():
                self._after_walls_complete()
                return
            if self._raid_once() <= 0:
                continue
            if not self._reached_threshold():
                continue
            self._upgrade_walls()
            if self._walls_done():
                self._after_walls_complete()
                return

    def _reached_threshold(self) -> bool:
        gold, elixir, _ = self._read_resources()
        total = gold + elixir
        threshold = self._threshold()
        if total > threshold:
            return True
        self.ctx.logger.info(
            "资源总和 %s 未达到升墙阈值 %s，继续打资源",
            total,
            threshold,
        )
        return False

    def _after_walls_complete(self) -> None:
        self.ctx.logger.info("城墙已无可升级项，停止打资源升墙循环")
        if self.farm_after_complete:
            self.ctx.logger.info("farm_after_complete 已开启，继续打资源到阈值")
            self._farm_to_threshold()

    def _farm_to_threshold(self) -> None:
        ctx = self.ctx
        threshold = self._threshold()
        while True:
            if self._limits_reached():
                return
            gold, elixir, _ = self._read_resources()
            total = gold + elixir
            if total > threshold:
                ctx.logger.info("资源总和 %s 超过阈值 %s，任务完成", total, threshold)
                return
            ctx.logger.info("资源总和 %s 未到阈值 %s，继续打资源", total, threshold)
            if self._raid_once() <= 0:
                continue

    def _threshold(self) -> float:
        full_gold = self.full_gold
        full_elixir = self.full_elixir
        if resources.MAX_LOADED:
            if resources.GOLD_MAX > 0:
                full_gold = resources.GOLD_MAX
            if resources.ELIXIR_MAX > 0:
                full_elixir = resources.ELIXIR_MAX
        return (full_gold + full_elixir) * self.threshold_ratio

    def _limits_reached(self) -> bool:
        ctx = self.ctx
        if ctx.should_stop():
            raise StopRequested("已请求停止")
        if self.max_cycles > 0 and self.memory.cycles >= self.max_cycles:
            ctx.logger.info("达到调度循环上限 %d", self.max_cycles)
            return True
        if self._runtime_exceeded(ctx, self.max_runtime_min):
            ctx.logger.info("达到最大运行时间 %.0f 分钟", self.max_runtime_min)
            return True
        return False

    def _walls_done(self) -> bool:
        return self.walls_complete

    def _can_afford_wall(self) -> bool:
        gold, elixir, _ = resources.snapshot()
        if self.wall_cost_gold > 0 and gold >= self.wall_cost_gold:
            return True
        return self.wall_cost_elixir > 0 and elixir >= self.wall_cost_elixir

    def _raid_once(self) -> int:
        ctx = self.ctx
        result = RaidTask(max_cycles=1).run(ctx)
        raids = int(result.counters.get("raids", 0))
        if raids <= 0:
            self.raid_failures += 1
            ctx.logger.warning(
                "本轮进攻没有结果 (%d/%d)",
                self.raid_failures,
                self.max_raid_retries,
            )
            if self.raid_failures >= self.max_raid_retries:
                raise TaskError("连续进攻没有结果，任务结束")
            ctx.sleep(3.0)
            return 0
        self.raid_failures = 0
        self.memory.raids += raids
        self.memory.cycles += 1
        ctx.sleep(1.5)
        self._ensure_home()
        resources.refresh(ctx, reason="进攻结束")
        self._last_gold, self._last_elixir, self._last_dark = resources.snapshot()
        self._save_state()
        return raids

    def _upgrade_walls(self) -> int:
        ctx = self.ctx
        result = WallUpgradeTask(
            max_upgrades=0,
            batch_size=self.wall_batch,
            min_total=int(self._threshold()),
        ).run(ctx)
        if result.status != "success":
            ctx.logger.warning("城墙任务状态 %s: %s", result.status, result.reason)
        upgraded = int(result.counters.get("wall_upgrades", 0))
        raw_remaining = result.counters.get("wall_remaining")
        if raw_remaining is not None and int(raw_remaining) >= 0:
            self.wall_remaining = int(raw_remaining)
            if self.wall_remaining == 0:
                self.walls_complete = True
        if int(result.counters.get("wall_complete", 0)):
            self.walls_complete = True
            self.wall_remaining = 0
        cost_gold = int(result.counters.get("wall_cost_gold", 0))
        cost_elixir = int(result.counters.get("wall_cost_elixir", 0))
        if cost_gold > 0:
            self.wall_cost_gold = cost_gold
        if cost_elixir > 0:
            self.wall_cost_elixir = cost_elixir
        self.memory.wall_upgrades += upgraded
        self.memory.gold_spent += int(result.counters.get("gold_spent", 0))
        self.memory.elixir_spent += int(result.counters.get("elixir_spent", 0))
        self._last_gold, self._last_elixir, self._last_dark = resources.snapshot()
        console.set_walls(
            self.wall_remaining,
            self.memory.wall_upgrades,
            complete=self.walls_complete,
            reason=f"升级城墙 {upgraded} 段",
        )
        self._save_state()
        if int(result.counters.get("wall_threshold_wait", 0)):
            ctx.logger.info("资源总和未达到升墙阈值，继续打资源")
            return 0
        if (
            upgraded <= 0
            and not self._walls_done()
            and self._can_afford_wall()
        ):
            ctx.logger.warning("资源足够但无法继续升级城墙")
            if not self._restart_and_retry():
                raise TaskError("城墙无法继续升级，重进游戏次数已用完")
            return self._upgrade_walls()
        return upgraded

    def _ensure_home(self) -> None:
        ensure_home(self.ctx)

    def _read_resources(self) -> tuple[int, int, int]:
        self._last_gold, self._last_elixir, self._last_dark = resources.snapshot()
        self._save_state()
        return self._last_gold, self._last_elixir, self._last_dark

    def _restart_and_retry(self) -> bool:
        ctx = self.ctx
        if self.max_restarts > 0 and self.restarts >= self.max_restarts:
            ctx.logger.error("重进游戏次数达到上限 %d", self.max_restarts)
            return False
        self.restarts += 1
        ctx.logger.warning(
            "城墙无法继续升级，重进游戏后重试 (%d/%d)",
            self.restarts,
            self.max_restarts,
        )
        try:
            restart_game(ctx)
        except StopRequested:
            raise
        except Exception:
            ctx.logger.exception("重进游戏失败")
            return False
        try:
            resources.refresh(ctx, reason="重进游戏")
        except StopRequested:
            raise
        except Exception:
            ctx.logger.exception("重进游戏后刷新资源失败")
        return True

    def _save_state(self) -> None:
        try:
            update_state(
                self.state_file,
                farm_updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                gold=self._last_gold,
                elixir=self._last_elixir,
                dark=self._last_dark,
                wall_remaining=self.wall_remaining,
                wall_upgraded=self.memory.wall_upgrades,
                wall_complete=self.walls_complete,
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
            f"升级城墙 {self.memory.wall_upgrades} 段"
        )
        if self.walls_complete:
            base += "，城墙已无可升级项"
        elif self.wall_remaining is not None:
            base += f"，剩余 {self.wall_remaining} 段"
        else:
            base += "，剩余数量未知"
        if self.restarts:
            base += f"，重进游戏 {self.restarts} 次"
        if status == "stopped":
            return base + "，已停止"
        if status == "failed":
            return base + "，失败"
        return base
