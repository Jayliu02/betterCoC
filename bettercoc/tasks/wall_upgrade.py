from __future__ import annotations

import json
import time
from dataclasses import dataclass

from ..context import Context
from ..errors import MissingAssetError, StopRequested, TaskError
from ..geometry import Rect
from ..ocr import parse_number
from ..recovery import ensure_home
from ..state import update_state
from ..state_machine import StateMachine
from .. import console, resources
from .base import Task, TaskResult

BUILD_BUTTON = "build_button"
WALL_ENTRY = "wall_entry"
HOME_GOLD = "home_gold"
HOME_ELIXIR = "home_elixir"
HOME_DARK = "home_dark"
WALL_COST_GOLD = "wall_cost_gold"
WALL_COST_ELIXIR = "wall_cost_elixir"


@dataclass
class WallMemory:
    upgrades: int = 0
    cycles: int = 0
    errors: int = 0
    gold: int = 0
    elixir: int = 0
    dark: int = 0
    gold_before: int = 0
    elixir_before: int = 0
    gold_spent: int = 0
    elixir_spent: int = 0
    pending_batch: int = 0
    pending_cost: int = 0
    pending_currency: str = ""
    fatal: bool = False


class WallUpgradeTask(Task):
    name = "wall_upgrade"

    def __init__(
        self,
        max_upgrades: int | None = None,
        batch_size: int | None = None,
        drain_all: bool = False,
    ) -> None:
        self._max_upgrades_override = max_upgrades
        self._batch_size_override = batch_size
        self.drain_all = drain_all
        self.drain_gold_done = False

    def run(self, ctx: Context) -> TaskResult:
        self.ctx = ctx
        self._begin(ctx)
        self.memory = WallMemory()
        self._load_settings()
        machine = StateMachine(ctx.logger)
        machine.add("prepare", self._prepare, on_error="recover")
        machine.add("open", self._open, on_error="recover")
        machine.add("reopen", self._reopen, on_error="recover")
        machine.add("select", self._select, on_error="recover")
        machine.add("upgrade", self._upgrade, on_error="recover")
        machine.add("decide", self._decide, on_error="recover")
        machine.add("recover", self._recover)
        machine.add("finish", self._finish)
        status = "success"
        reason = ""
        try:
            machine.run("prepare")
            if ctx.should_stop():
                status = "stopped"
            if self.memory.fatal:
                status = "failed"
            self._return_home()
            self._read_final_resources()
            reason = self._summary(status)
        except StopRequested as exc:
            status = "stopped"
            reason = self._summary("stopped")
            ctx.logger.info("任务停止: %s", exc)
        except Exception:
            try:
                ctx.save_screenshot("wall-upgrade-error")
            except Exception:
                ctx.logger.exception("保存错误截图失败")
            raise
        finally:
            ctx.stats.set("wall_upgrades", self.memory.upgrades)
            ctx.stats.set("cycles", self.memory.cycles)
            ctx.stats.set("gold_spent", self.memory.gold_spent)
            ctx.stats.set("elixir_spent", self.memory.elixir_spent)
            if self.wall_remaining is not None:
                ctx.stats.set("wall_remaining", self.wall_remaining)
        transitions = [
            {
                "from": item.source,
                "to": item.target,
                "elapsed": round(item.elapsed, 3),
            }
            for item in machine.transitions
        ]
        return TaskResult(
            task=self.name,
            status=status,
            reason=reason,
            counters=ctx.stats.to_dict(),
            elapsed=self._task_elapsed(ctx),
            transitions=transitions,
        )

    def _load_settings(self) -> None:
        cfg = self.ctx.config
        self.max_upgrades = int(cfg.get("task.wall_upgrade.max_upgrades", 10))
        if self._max_upgrades_override is not None:
            self.max_upgrades = self._max_upgrades_override
        self.batch_size = max(0, int(cfg.get("task.wall_upgrade.batch_size", 10)))
        if self._batch_size_override is not None:
            self.batch_size = max(0, self._batch_size_override)
        self.max_errors = int(cfg.get("task.wall_upgrade.max_errors", 2))
        self.max_cycles = int(cfg.get("task.wall_upgrade.max_cycles", 10))
        self.max_runtime_min = float(cfg.get("task.wall_upgrade.max_runtime_min", 15))
        self.cost_per_wall = int(cfg.get("task.wall_upgrade.cost_per_wall", 0))
        self.prefer_currency = str(
            cfg.get("task.wall_upgrade.prefer_currency", "auto")
        ).lower()
        self.scroll_times = max(1, int(cfg.get("task.wall_upgrade.scroll_times", 10)))
        self.scroll_duration = int(cfg.get("task.wall_upgrade.scroll_duration_ms", 400))
        self.settle = float(cfg.get("task.wall_upgrade.settle_ms", 1500)) / 1000.0
        self.state_file = cfg.resolve_path(
            cfg.get("task.wall_upgrade.state_file", "runtime/resource-state.json")
        )
        self.max_resource = int(
            cfg.get("task.wall_upgrade.max_resource", 20_000_000)
        )
        self.wall_remaining: int | None = None
        self.current_remaining: int | None = None
        self.last_cost_gold = 0
        self.last_cost_elixir = 0
        self._buttons_saved = False
        self.gold_button = self._point(
            cfg.get("task.wall_upgrade.gold_button", [487, 930]),
            "task.wall_upgrade.gold_button",
        )
        self.elixir_button = self._point(
            cfg.get("task.wall_upgrade.elixir_button", [707, 930]),
            "task.wall_upgrade.elixir_button",
        )
        self.more_point = self._point(
            cfg.get("task.wall_upgrade.more_point", [925, 753]),
            "task.wall_upgrade.more_point",
        )
        self.add_one_point = self._point(
            cfg.get("task.wall_upgrade.add_wall_point", [908, 760]),
            "task.wall_upgrade.add_wall_point",
        )
        self.add_ten_point = self._point(
            cfg.get("task.wall_upgrade.add_ten_point", [710, 755]),
            "task.wall_upgrade.add_ten_point",
        )
        self.confirm_point = self._point(
            cfg.get("task.wall_upgrade.confirm_point", [1168, 707]),
            "task.wall_upgrade.confirm_point",
        )

    def _point(self, raw, name: str) -> tuple[int, int]:
        try:
            if isinstance(raw, dict):
                return int(raw["x"]), int(raw["y"])
            return int(raw[0]), int(raw[1])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise TaskError(f"{name} 坐标格式错误: {raw!r}") from exc

    def _prepare(self) -> str:
        self._ensure_home()
        resources.ensure_loaded(self.ctx)
        self.memory.gold, self.memory.elixir, self.memory.dark = resources.snapshot()
        if self.memory.gold_before == 0 and self.memory.elixir_before == 0:
            self.memory.gold_before = self.memory.gold
            self.memory.elixir_before = self.memory.elixir
        self.ctx.logger.info(
            "当前资源: 金币 %s，圣水 %s，暗黑 %s",
            self.memory.gold,
            self.memory.elixir,
            self.memory.dark,
        )
        self._save_state()
        self._save_buttons(self.ctx)
        return "open"

    def _ensure_home(self) -> None:
        ensure_home(self.ctx)

    def _read_home_resources(self) -> None:
        self.memory.gold, self.memory.elixir, self.memory.dark = resources.snapshot()

    def _read_final_resources(self) -> None:
        self.memory.gold, self.memory.elixir, self.memory.dark = resources.snapshot()
        self._save_state()

    def _save_state(self) -> None:
        try:
            update_state(
                self.state_file,
                updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                gold=self.memory.gold,
                elixir=self.memory.elixir,
                dark=self.memory.dark,
                gold_before=self.memory.gold_before,
                elixir_before=self.memory.elixir_before,
                gold_spent=self.memory.gold_spent,
                elixir_spent=self.memory.elixir_spent,
                wall_upgrades=self.memory.upgrades,
                wall_remaining=(
                    self.current_remaining
                    if self.current_remaining is not None
                    else self.wall_remaining
                ),
            )
        except OSError:
            self.ctx.logger.exception("写入资源状态失败")

    def _read_number(self, name: str, screen, default: int) -> int:
        ctx = self.ctx
        if not ctx.vision.assets.has(name):
            return default
        try:
            match = ctx.find(name, screen=screen)
        except MissingAssetError:
            return default
        value = parse_number(match.text if match else None)
        return default if value is None else value

    def _open(self) -> str:
        ctx = self.ctx
        ctx.click(BUILD_BUTTON, timeout=6)
        ctx.sleep(0.8)
        entry = self._find_wall_entry()
        if entry is None:
            raise TaskError("建造栏中找不到城墙入口")
        self._read_wall_remaining(entry)
        self._enter_batch(entry)
        return "select"

    def _enter_batch(self, entry) -> None:
        ctx = self.ctx
        ctx.tap_match(entry)
        ctx.sleep(1.2)
        ctx.tap(*self.more_point)
        ctx.sleep(1.5)

    def _read_wall_remaining(self, entry, reset: bool = True) -> None:
        ctx = self.ctx
        if ctx.vision.digits is None:
            return
        roi = Rect(entry.rect.x + 115, entry.rect.y - 19, 120, 50)
        value, text, score = ctx.vision.digits.read(ctx.screen(), roi)
        if value is not None:
            if reset:
                self.wall_remaining = value
            self.current_remaining = value
            ctx.logger.info("城墙剩余 %s 段，识别分 %.2f", value, score)
            console.set_walls(value, reason="读取城墙数量")

    def _find_wall_entry(self):
        ctx = self.ctx
        entry = ctx.find(WALL_ENTRY)
        if entry is not None:
            return entry
        for _ in range(self.scroll_times):
            ctx.swipe(1500, 750, 1500, 300, self.scroll_duration)
            ctx.sleep(0.3)
            entry = ctx.find(WALL_ENTRY)
            if entry is not None:
                return entry
        return None

    def _select(self) -> str:
        ctx = self.ctx
        if self.memory.cycles >= self.max_cycles:
            ctx.logger.info("达到城墙升级循环上限 %d", self.max_cycles)
            return "finish"
        if self._runtime_exceeded(ctx, self.max_runtime_min):
            ctx.logger.info("达到城墙升级运行时长 %.0f 分钟", self.max_runtime_min)
            return "finish"
        cost_gold = self._read_number(WALL_COST_GOLD, None, 0)
        cost_elixir = self._read_number(WALL_COST_ELIXIR, None, 0)
        if cost_gold <= 0 or cost_elixir <= 0:
            fallback = self.cost_per_wall
            if cost_gold <= 0:
                cost_gold = fallback
            if cost_elixir <= 0:
                cost_elixir = fallback
        if cost_gold <= 0 or cost_elixir <= 0:
            raise TaskError("无法读取城墙升级成本")
        if cost_gold < 10_000:
            cost_gold = self.cost_per_wall
        if cost_elixir < 10_000:
            cost_elixir = self.cost_per_wall
        if cost_gold <= 0 or cost_elixir <= 0:
            raise TaskError("城墙升级成本无效")
        self.last_cost_gold = cost_gold
        self.last_cost_elixir = cost_elixir
        remaining = max(0, self.max_upgrades - self.memory.upgrades)
        affordable = max(
            self.memory.gold // cost_gold, self.memory.elixir // cost_elixir
        )
        batch_limit = self.batch_size if self.batch_size > 0 else remaining
        if self.drain_all:
            gold_count = self.memory.gold // cost_gold
            elixir_count = self.memory.elixir // cost_elixir
            if not self.drain_gold_done and gold_count > 0:
                batch = min(gold_count, remaining, 30)
                use_gold = True
            elif elixir_count > 0:
                batch = min(elixir_count, remaining, 30)
                use_gold = False
            else:
                batch = 0
                use_gold = True
        else:
            batch = min(batch_limit, remaining, affordable, 30)
            total_gold = cost_gold * batch
            total_elixir = cost_elixir * batch
            can_gold = self.memory.gold >= total_gold
            can_elixir = self.memory.elixir >= total_elixir
            if self.prefer_currency == "gold":
                use_gold = can_gold
            elif self.prefer_currency == "elixir":
                use_gold = not can_elixir
            else:
                use_gold = can_gold
        ctx.logger.info(
            "单段成本 金币 %s / 圣水 %s，当前资源可升级 %s 段",
            cost_gold,
            cost_elixir,
            affordable,
        )
        if batch <= 0:
            ctx.logger.info(
                "资源不足：金币 %s / 圣水 %s，单段成本 %s/%s",
                self.memory.gold,
                self.memory.elixir,
                cost_gold,
                cost_elixir,
            )
            return "finish"
        total_gold = cost_gold * batch
        total_elixir = cost_elixir * batch
        can_gold = self.memory.gold >= total_gold
        can_elixir = self.memory.elixir >= total_elixir
        if self.prefer_currency == "gold":
            use_gold = can_gold
        elif self.prefer_currency == "elixir":
            use_gold = not can_elixir
        else:
            use_gold = can_gold
        if use_gold and not can_gold:
            return "finish"
        if not use_gold and not can_elixir:
            return "finish"
        self._select_batch(batch)
        ctx.logger.info(
            "选择 %d 段城墙，成本 金币 %s / 圣水 %s，使用 %s",
            batch,
            total_gold,
            total_elixir,
            "金币" if use_gold else "圣水",
        )
        gold_point, elixir_point = self.gold_button, self.elixir_button
        if use_gold:
            ctx.tap(*gold_point)
            self.memory.pending_cost = total_gold
            self.memory.pending_currency = "gold"
        else:
            ctx.tap(*elixir_point)
            self.memory.pending_cost = total_elixir
            self.memory.pending_currency = "elixir"
        self.memory.pending_batch = batch
        return "upgrade"

    def _select_batch(self, target: int) -> None:
        ctx = self.ctx
        selected = 1
        while target - selected >= 10:
            ctx.tap(*self.add_ten_point)
            selected += 10
            ctx.sleep(0.25)
        while selected < target:
            ctx.tap(*self.add_one_point)
            selected += 1
            ctx.sleep(0.2)

    def _save_buttons(self, ctx) -> None:
        if self._buttons_saved:
            return
        self._buttons_saved = True
        path = ctx.config.resolve_path(
            ctx.config.get(
                "task.wall_upgrade.buttons_file", "runtime/wall-buttons.json"
            )
        )
        data = {
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "more": list(self.more_point),
            "add_one": list(self.add_one_point),
            "add_ten": list(self.add_ten_point),
            "gold_upgrade": list(self.gold_button),
            "elixir_upgrade": list(self.elixir_button),
            "confirm": list(self.confirm_point),
            "source": "固定位置",
            "confirmed": True,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            ctx.logger.info("升墙按钮坐标已保存: %s", path)
        except OSError:
            ctx.logger.exception("保存升墙按钮坐标失败")

    def _upgrade(self) -> str:
        ctx = self.ctx
        ctx.sleep(1.5)
        ctx.tap(*self.confirm_point)
        ctx.sleep(self.settle)
        batch = self.memory.pending_batch
        if self.memory.pending_currency == "gold":
            self.drain_gold_done = True
            self.memory.gold_spent += self.memory.pending_cost
            self.memory.gold = max(0, self.memory.gold - self.memory.pending_cost)
            resources.adjust(
                gold=-self.memory.pending_cost,
                reason=f"升级城墙 {batch} 段",
            )
        else:
            self.memory.elixir_spent += self.memory.pending_cost
            self.memory.elixir = max(0, self.memory.elixir - self.memory.pending_cost)
            resources.adjust(
                elixir=-self.memory.pending_cost,
                reason=f"升级城墙 {batch} 段",
            )
        if self.current_remaining is not None:
            self.current_remaining = max(0, self.current_remaining - batch)
            console.set_walls(self.current_remaining, reason=f"升级城墙 {batch} 段")
        self.memory.upgrades += batch
        self.memory.cycles += 1
        ctx.logger.info("城墙升级完成 %d 段，总计 %d 段", batch, self.memory.upgrades)
        return "decide"

    def _reopen(self) -> str:
        ctx = self.ctx
        ctx.logger.info("保持当前侧边栏，直接再次进入城墙")
        entry = self._find_wall_entry()
        if entry is None:
            ctx.logger.warning("侧边栏找不到城墙入口，重新打开建造")
            return self._open()
        self._read_wall_remaining(entry, reset=False)
        self._enter_batch(entry)
        return "select"

    def _return_home(self) -> None:
        ensure_home(self.ctx, label="主界面")

    def _decide(self) -> str:
        ctx = self.ctx
        if ctx.should_stop():
            return "finish"
        if self.memory.upgrades >= self.max_upgrades:
            ctx.logger.info("达到升级上限 %d 段", self.max_upgrades)
            return "finish"
        if (
            self.last_cost_gold > 0
            and self.memory.gold < self.last_cost_gold
            and self.memory.elixir < self.last_cost_elixir
        ):
            ctx.logger.info("剩余资源不足单段成本，结束本轮城墙升级")
            return "finish"
        if self.memory.gold <= 0 and self.memory.elixir <= 0:
            return "finish"
        return "reopen"

    def _recover(self) -> str:
        ctx = self.ctx
        self.memory.errors += 1
        ctx.stats.incr("recoveries")
        if self.memory.errors > self.max_errors:
            ctx.logger.error("恢复次数超过上限，任务结束")
            self.memory.fatal = True
            return "finish"
        ctx.logger.warning("执行恢复流程 (%d/%d)", self.memory.errors, self.max_errors)
        try:
            self._return_home()
        except StopRequested:
            raise
        except Exception:
            ctx.logger.exception("恢复失败")
            self.memory.fatal = True
            return "finish"
        return "prepare"

    def _finish(self) -> None:
        return None

    def _summary(self, status: str) -> str:
        base = (
            f"升级城墙 {self.memory.upgrades} 段，花费金币 {self.memory.gold_spent}，"
            f"圣水 {self.memory.elixir_spent}"
        )
        if self.memory.gold_before or self.memory.elixir_before:
            base += (
                f"；金币 {self.memory.gold_before} -> {self.memory.gold}，"
                f"圣水 {self.memory.elixir_before} -> {self.memory.elixir}"
            )
        if self.memory.errors:
            base += f"，恢复 {self.memory.errors} 次"
        if status == "stopped":
            return base + "，已停止"
        if status == "failed":
            return base + "，失败"
        return base
