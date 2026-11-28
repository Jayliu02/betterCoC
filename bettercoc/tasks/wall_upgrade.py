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
WALL_ENTRY_15 = "wall_entry_15"
WALL_ENTRY_16 = "wall_entry_16"
WALL_ROW_LABEL = "wall_row_label"
WALL_BATCH_ADD = "wall_add_1"
WALL_BATCH_TEN = "wall_add_10"
WALL_BATCH_REMOVE = "wall_batch_remove"
WALL_MORE = "wall_more"
WALL_CONFIRM = "wall_confirm"
SIDE_PANEL_CLOSE = "side_panel_close"
WALL_COST_GOLD = "wall_cost_gold"
WALL_COST_ELIXIR = "wall_cost_elixir"

MAX_BATCH = 30
WALL_PANEL_ROI = Rect(1370, 30, 550, 1010)


def plan_batch(
    remaining: int | None,
    affordable: int,
    batch_size: int,
    upgrades_left: int | None,
    unknown_batch: int = 10,
    max_batch: int = MAX_BATCH,
) -> int:
    if affordable <= 0:
        return 0
    if upgrades_left is not None and upgrades_left <= 0:
        return 0
    cap = max(0, max_batch)
    if batch_size > 0:
        cap = min(cap, batch_size)
    if upgrades_left is not None:
        cap = min(cap, upgrades_left)
    if remaining is None:
        cap = min(cap, max(1, unknown_batch) if batch_size <= 0 else batch_size)
    else:
        cap = min(cap, max(0, remaining))
    return max(0, min(cap, affordable))


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
    complete: bool = False
    no_batch: int = 0
    threshold_wait: bool = False
    stop_reason: str = ""
    fatal: bool = False


class WallUpgradeTask(Task):
    name = "wall_upgrade"

    def __init__(
        self,
        max_upgrades: int | None = None,
        batch_size: int | None = None,
        min_total: int | None = None,
    ) -> None:
        self._max_upgrades_override = max_upgrades
        self._batch_size_override = batch_size
        self._min_total_override = min_total

    def run(self, ctx: Context) -> TaskResult:
        self.ctx = ctx
        self._begin(ctx)
        self.memory = WallMemory()
        self._load_settings()
        for key, value in (
            ("wall_upgrades", 0),
            ("wall_remaining", -1),
            ("wall_complete", 0),
            ("wall_cost_gold", 0),
            ("wall_cost_elixir", 0),
        ):
            ctx.stats.set(key, value)
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
            ctx.stats.set(
                "wall_remaining", -1 if self.remaining is None else self.remaining
            )
            ctx.stats.set("wall_complete", 1 if self.memory.complete else 0)
            ctx.stats.set(
                "wall_threshold_wait", 1 if self.memory.threshold_wait else 0
            )
            ctx.stats.set("wall_cost_gold", self.last_cost_gold)
            ctx.stats.set("wall_cost_elixir", self.last_cost_elixir)
            console.set_walls(
                self.remaining,
                self.memory.upgrades,
                complete=self.memory.complete,
                reason=self.memory.stop_reason,
            )
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
        self.max_upgrades = int(cfg.get("task.wall_upgrade.max_upgrades", 0))
        if self._max_upgrades_override is not None:
            self.max_upgrades = self._max_upgrades_override
        self.min_total = int(cfg.get("task.wall_upgrade.min_total", 0))
        if self._min_total_override is not None:
            self.min_total = max(0, self._min_total_override)
        self.batch_size = max(0, int(cfg.get("task.wall_upgrade.batch_size", 10)))
        if self._batch_size_override is not None:
            self.batch_size = max(0, self._batch_size_override)
        self.unknown_batch = max(
            1, int(cfg.get("task.wall_upgrade.unknown_batch_size", 10))
        )
        self.max_batch = min(
            MAX_BATCH, max(1, int(cfg.get("task.wall_upgrade.max_batch", 9)))
        )
        self.max_walls = max(1, int(cfg.get("task.wall_upgrade.max_walls", 500)))
        self.complete_on_no_batch = bool(
            cfg.get("task.wall_upgrade.complete_on_no_batch", True)
        )
        self.max_errors = int(cfg.get("task.wall_upgrade.max_errors", 2))
        self.max_cycles = int(cfg.get("task.wall_upgrade.max_cycles", 0))
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
        self.remaining_offset = self._offset(
            cfg.get("task.wall_upgrade.remaining_offset", [115, -19, 120, 50]),
            "task.wall_upgrade.remaining_offset",
        )
        self.icon_remaining_offset = self._offset(
            cfg.get("task.wall_upgrade.icon_remaining_offset", [115, -14, 120, 45]),
            "task.wall_upgrade.icon_remaining_offset",
        )
        self.remaining: int | None = None
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

    def _offset(self, raw, name: str) -> tuple[int, int, int, int]:
        try:
            dx, dy, width, height = (int(value) for value in raw)
        except (TypeError, ValueError) as exc:
            raise TaskError(f"{name} 格式应为 [dx, dy, w, h]: {raw!r}") from exc
        if width <= 0 or height <= 0:
            raise TaskError(f"{name} 宽高必须为正数: {raw!r}")
        return dx, dy, width, height

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
        total = self.memory.gold + self.memory.elixir
        if self.min_total > 0 and total < self.min_total:
            self.memory.threshold_wait = True
            self.memory.stop_reason = (
                f"资源总和 {total} 未达到升级阈值 {self.min_total}"
            )
            self.ctx.logger.info(self.memory.stop_reason)
            self._save_state()
            self._save_buttons(self.ctx)
            return "finish"
        self._save_state()
        self._save_buttons(self.ctx)
        return "open"

    def _ensure_home(self) -> None:
        ensure_home(self.ctx)

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
                wall_upgraded=self.memory.upgrades,
                wall_remaining=self.remaining,
                wall_complete=self.memory.complete,
                wall_cost_gold=self.last_cost_gold,
                wall_cost_elixir=self.last_cost_elixir,
            )
        except OSError:
            self.ctx.logger.exception("写入资源状态失败")

    def _read_cost(self, name: str, screen) -> tuple[int | None, float]:
        ctx = self.ctx
        if not ctx.vision.assets.has(name):
            return None, 0.0
        try:
            match = ctx.find(name, screen=screen)
        except MissingAssetError:
            return None, 0.0
        value = parse_number(match.text if match else None)
        score = match.score if match is not None else 0.0
        return value, score

    def _settle_costs(self, screen) -> tuple[int, int]:
        gold, gold_score = self._read_cost(WALL_COST_GOLD, screen)
        elixir, elixir_score = self._read_cost(WALL_COST_ELIXIR, screen)
        gold_ok = gold is not None and gold >= 10_000
        elixir_ok = elixir is not None and elixir >= 10_000
        if gold_ok and elixir_ok:
            if gold != elixir:
                if gold_score >= elixir_score:
                    elixir = gold
                else:
                    gold = elixir
        elif gold_ok:
            elixir = gold
        elif elixir_ok:
            gold = elixir
        else:
            gold = self.cost_per_wall
            elixir = self.cost_per_wall
        return gold, elixir

    def _open(self) -> str:
        ctx = self.ctx
        ctx.click(BUILD_BUTTON, timeout=6)
        ctx.sleep(0.8)
        choice, saw_rows = self._next_wall_row_settled()
        if choice is None:
            if saw_rows:
                self._mark_complete("建造栏显示城墙已无可升级项")
                return "finish"
            if self._build_panel_open():
                raise TaskError(
                    "建造栏没有识别到城墙行，检查 wall_row_label / wall_entry 模板"
                )
            raise TaskError("建造栏中找不到城墙入口")
        return self._enter_wall_batch(choice)

    def _enter_wall_batch(self, choice) -> str:
        ctx = self.ctx
        entry, remaining = choice
        self.remaining = remaining
        if remaining is None:
            ctx.logger.warning("无法读取城墙可升级数量，按小批量处理")
            console.set_walls(
                None,
                self.memory.upgrades,
                complete=False,
                reason="读取城墙数量",
            )
        else:
            ctx.logger.info(
                "选择城墙行 y=%s（%s），可升级 %s 段",
                entry.rect.y,
                entry.name,
                remaining,
            )
            console.set_walls(
                remaining,
                self.memory.upgrades,
                complete=False,
                reason="读取城墙数量",
            )
        if not self._enter_batch(entry):
            if remaining is None and self.complete_on_no_batch:
                self.memory.no_batch += 1
                ctx.logger.warning(
                    "城墙批量升级界面没有打开 (%d 次)", self.memory.no_batch
                )
                if self.memory.no_batch >= 2:
                    self._mark_complete(
                        "批量升级界面连续未打开，按无可升级城墙处理"
                    )
                    return "finish"
            raise TaskError("城墙批量升级界面没有打开")
        self.memory.no_batch = 0
        return "select"

    def _enter_batch(self, entry) -> bool:
        ctx = self.ctx
        for _ in range(2):
            self._tap_row(entry)
            ctx.sleep(1.2)
            screen = ctx.screen()
            if self._batch_visible(screen):
                return True
            if not self._wall_panel_visible(screen):
                continue
            ctx.tap(*self.more_point)
            ctx.sleep(1.5)
            screen = ctx.screen()
            if self._batch_visible(screen):
                return True
            if not self._wall_panel_visible(screen):
                return False
            ctx.logger.warning("城墙批量升级界面没有出现，再试一次")
            ctx.tap(*self.more_point)
            ctx.sleep(1.5)
            if self._batch_visible(ctx.screen()):
                return True
        return False

    def _tap_row(self, entry) -> None:
        if entry.name == WALL_ROW_LABEL:
            self.ctx.tap(entry.rect.x - 35, entry.rect.center[1])
        else:
            self.ctx.tap_match(entry)

    def _wall_panel_visible(self, screen=None) -> bool:
        if not self.ctx.vision.assets.has(WALL_MORE):
            return True
        return self.ctx.find_optional(WALL_MORE, screen=screen) is not None

    def _batch_visible(self, screen) -> bool:
        checked = False
        if self.ctx.vision.assets.has(WALL_BATCH_REMOVE):
            checked = True
            if self.ctx.find_optional(WALL_BATCH_REMOVE, screen=screen) is not None:
                return True
        names = [
            name
            for name in (WALL_BATCH_ADD, WALL_BATCH_TEN)
            if self.ctx.vision.assets.has(name)
        ]
        if names:
            checked = True
            if any(
                self.ctx.find_optional(name, screen=screen) is not None
                for name in names
            ):
                return True
        return not checked

    def _build_panel_open(self) -> bool:
        return self.ctx.find_optional(SIDE_PANEL_CLOSE) is not None

    def _visible_wall_rows(self, screen) -> list:
        rows = []
        if self.ctx.vision.assets.has(WALL_ROW_LABEL):
            rows.extend(
                self.ctx.find_all(
                    WALL_ROW_LABEL,
                    screen=screen,
                    roi=WALL_PANEL_ROI,
                    limit=20,
                )
            )
        else:
            self.ctx.logger.warning(
                "未加载 wall_row_label 模板，回退城墙图标；如刚添加模板请重启进程"
            )
        for name in (WALL_ENTRY_15, WALL_ENTRY_16, WALL_ENTRY):
            if not self.ctx.vision.assets.has(name):
                continue
            rows.extend(
                self.ctx.find_all(
                    name,
                    screen=screen,
                    roi=WALL_PANEL_ROI,
                    limit=20,
                )
            )
        return self._dedupe_rows(rows)

    def _dedupe_rows(self, matches) -> list:
        rows = []
        for match in matches:
            if any(abs(match.rect.y - row.rect.y) <= 40 for row in rows):
                continue
            rows.append(match)
        rows.sort(key=lambda row: row.rect.y)
        return rows

    def _count_roi(self, row) -> Rect:
        if row.name == WALL_ROW_LABEL:
            return Rect(row.rect.right + 2, row.rect.y - 3, 110, 45)
        if row.name in (WALL_ENTRY_15, WALL_ENTRY_16):
            dx, dy, width, height = self.icon_remaining_offset
            return Rect(row.rect.x + dx, row.rect.y + dy, width, height)
        dx, dy, width, height = self.remaining_offset
        return Rect(row.rect.x + dx, row.rect.y + dy, width, height)

    def _read_rows(self, rows, screen) -> list[tuple]:
        if not rows:
            return []
        if self.ctx.vision.digits is None:
            return [(row, None) for row in rows]
        result = []
        for row in rows:
            roi = self._count_roi(row)
            value, text, score = self.ctx.vision.digits.read(screen, roi)
            if value is not None and not 0 <= value <= self.max_walls:
                self.ctx.logger.warning(
                    "城墙可升级数量 %s 超出合理范围 0-%s，忽略本次读数",
                    value,
                    self.max_walls,
                )
                value = None
            elif value is not None:
                self.ctx.logger.info(
                    "城墙行 %s y=%s 可升级 %s 段，识别分 %.2f",
                    row.name,
                    row.rect.y,
                    value,
                    score,
                )
            result.append((row, value))
        return result

    def _preferred_row(self, rows) -> tuple | None:
        positive = [
            (row, value) for row, value in rows if value is not None and value > 0
        ]
        if positive:
            return positive[0]
        unknown = [(row, value) for row, value in rows if value is None]
        if unknown:
            return unknown[0]
        return None

    def _scroll_to_top(self) -> None:
        for _ in range(self.scroll_times):
            self.ctx.swipe(1500, 300, 1500, 750, self.scroll_duration)
            self.ctx.sleep(0.2)

    def _scroll_down(self) -> None:
        self.ctx.swipe(1500, 750, 1500, 300, self.scroll_duration)
        self.ctx.sleep(0.3)

    def _next_wall_row_settled(self) -> tuple[tuple | None, bool]:
        choice, saw_rows = self._next_wall_row()
        if choice is not None:
            return choice, saw_rows
        self.ctx.sleep(1.0)
        choice, saw_again = self._next_wall_row()
        return choice, saw_rows or saw_again

    def _next_wall_row(self) -> tuple[tuple | None, bool]:
        ctx = self.ctx
        screen = ctx.screen()
        rows = self._visible_wall_rows(screen)
        if not rows:
            ctx.sleep(0.8)
            screen = ctx.screen()
            rows = self._visible_wall_rows(screen)
        saw_rows = bool(rows)
        if rows:
            choice = self._preferred_row(self._read_rows(rows, screen))
            if choice is not None:
                return choice, True
        self._scroll_to_top()
        screen = ctx.screen()
        rows = self._visible_wall_rows(screen)
        saw_rows = saw_rows or bool(rows)
        choice = self._preferred_row(self._read_rows(rows, screen))
        if choice is not None:
            return choice, saw_rows
        for _ in range(self.scroll_times):
            self._scroll_down()
            screen = ctx.screen()
            rows = self._visible_wall_rows(screen)
            saw_rows = saw_rows or bool(rows)
            choice = self._preferred_row(self._read_rows(rows, screen))
            if choice is not None:
                return choice, saw_rows
        return None, saw_rows

    def _mark_complete(self, reason: str) -> None:
        self.memory.complete = True
        self.memory.stop_reason = reason
        self.remaining = 0
        self.ctx.logger.info("城墙已无可升级项: %s", reason)
        console.set_walls(
            0,
            self.memory.upgrades,
            complete=True,
            reason=reason,
        )

    def _select(self) -> str:
        ctx = self.ctx
        if self.max_cycles > 0 and self.memory.cycles >= self.max_cycles:
            ctx.logger.info("达到城墙升级循环上限 %d", self.max_cycles)
            self.memory.stop_reason = "达到循环上限"
            return "finish"
        if self._runtime_exceeded(ctx, self.max_runtime_min):
            ctx.logger.info("达到城墙升级运行时长 %.0f 分钟", self.max_runtime_min)
            self.memory.stop_reason = "达到运行时长上限"
            return "finish"
        if self.remaining is not None and self.remaining <= 0:
            self._mark_complete("没有可升级城墙")
            return "finish"
        cost_gold, cost_elixir = self._settle_costs(None)
        if cost_gold <= 0 or cost_elixir <= 0:
            raise TaskError("无法读取城墙升级成本")
        self.last_cost_gold = cost_gold
        self.last_cost_elixir = cost_elixir
        upgrades_left = (
            None
            if self.max_upgrades <= 0
            else max(0, self.max_upgrades - self.memory.upgrades)
        )
        affordable = max(
            self.memory.gold // cost_gold, self.memory.elixir // cost_elixir
        )
        batch = plan_batch(
            self.remaining,
            affordable,
            self.batch_size,
            upgrades_left,
            self.unknown_batch,
            self.max_batch,
        )
        ctx.logger.info(
            "单段成本 金币 %s / 圣水 %s，当前资源可升级 %s 段，城墙可升级 %s",
            cost_gold,
            cost_elixir,
            affordable,
            "未知" if self.remaining is None else f"{self.remaining} 段",
        )
        if batch <= 0:
            if upgrades_left is not None and upgrades_left <= 0:
                ctx.logger.info("达到升级上限 %d 段", self.max_upgrades)
                self.memory.stop_reason = "达到升级上限"
            else:
                ctx.logger.info(
                    "资源不足：金币 %s / 圣水 %s，单段成本 %s/%s",
                    self.memory.gold,
                    self.memory.elixir,
                    cost_gold,
                    cost_elixir,
                )
                self.memory.stop_reason = "资源不足"
            return "finish"
        currency = self._choose_currency(batch, cost_gold, cost_elixir)
        if currency is None:
            ctx.logger.info("两种货币都不足 %d 段城墙", batch)
            self.memory.stop_reason = "资源不足"
            return "finish"
        total = (cost_gold if currency == "gold" else cost_elixir) * batch
        self._select_batch(batch)
        ctx.logger.info(
            "选择 %d 段城墙，成本 金币 %s / 圣水 %s，使用 %s",
            batch,
            cost_gold * batch,
            cost_elixir * batch,
            "金币" if currency == "gold" else "圣水",
        )
        if currency == "gold":
            ctx.tap(*self.gold_button)
        else:
            ctx.tap(*self.elixir_button)
        self.memory.pending_cost = total
        self.memory.pending_currency = currency
        self.memory.pending_batch = batch
        return "upgrade"

    def _choose_currency(self, batch: int, cost_gold: int, cost_elixir: int) -> str | None:
        total_gold = cost_gold * batch
        total_elixir = cost_elixir * batch
        can_gold = self.memory.gold >= total_gold
        can_elixir = self.memory.elixir >= total_elixir
        if self.prefer_currency == "gold":
            if can_gold:
                return "gold"
            return "elixir" if can_elixir else None
        if self.prefer_currency == "elixir":
            if can_elixir:
                return "elixir"
            return "gold" if can_gold else None
        if can_gold:
            return "gold"
        return "elixir" if can_elixir else None

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
        ctx.sleep(0.8)
        if ctx.vision.assets.has(WALL_CONFIRM):
            confirm = ctx.try_wait(WALL_CONFIRM, timeout=4)
            if confirm is None:
                ctx.logger.warning("城墙升级确认按钮没有出现")
                raise TaskError("城墙升级确认按钮没有出现")
            ctx.tap_match(confirm)
        else:
            ctx.tap(*self.confirm_point)
        ctx.sleep(self.settle)
        batch = self.memory.pending_batch
        if self.memory.pending_currency == "gold":
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
        if self.remaining is not None:
            self.remaining = None
        self.memory.upgrades += batch
        self.memory.cycles += 1
        self.memory.pending_batch = 0
        self.memory.pending_cost = 0
        self.memory.pending_currency = ""
        ctx.logger.info("城墙升级完成 %d 段，总计 %d 段", batch, self.memory.upgrades)
        return "decide"

    def _reopen(self) -> str:
        ctx = self.ctx
        ctx.logger.info("保持当前侧边栏，直接再次进入城墙")
        choice, saw_rows = self._next_wall_row_settled()
        if choice is None:
            if saw_rows:
                self._mark_complete("建造栏显示城墙已无可升级项")
                return "finish"
            if self._build_panel_open():
                raise TaskError(
                    "建造栏没有识别到城墙行，检查 wall_row_label / wall_entry 模板"
                )
            return self._open()
        return self._enter_wall_batch(choice)

    def _return_home(self) -> None:
        ensure_home(self.ctx, label="主界面")

    def _decide(self) -> str:
        ctx = self.ctx
        if ctx.should_stop():
            self.memory.stop_reason = "已停止"
            return "finish"
        if self.max_upgrades > 0 and self.memory.upgrades >= self.max_upgrades:
            ctx.logger.info("达到升级上限 %d 段", self.max_upgrades)
            self.memory.stop_reason = "达到升级上限"
            return "finish"
        if (
            self.last_cost_gold > 0
            and self.memory.gold < self.last_cost_gold
            and self.memory.elixir < self.last_cost_elixir
        ):
            ctx.logger.info("剩余资源不足单段成本，结束本轮城墙升级")
            self.memory.stop_reason = "资源不足"
            return "finish"
        if self.memory.gold <= 0 and self.memory.elixir <= 0:
            self.memory.stop_reason = "资源不足"
            return "finish"
        return "reopen"

    def _recover(self) -> str:
        ctx = self.ctx
        self.memory.errors += 1
        ctx.stats.incr("recoveries")
        if self.memory.errors > self.max_errors:
            ctx.logger.error("恢复次数超过上限，任务结束")
            self.memory.fatal = True
            self.memory.stop_reason = "恢复次数超过上限"
            return "finish"
        ctx.logger.warning("执行恢复流程 (%d/%d)", self.memory.errors, self.max_errors)
        try:
            self._return_home()
        except StopRequested:
            raise
        except Exception:
            ctx.logger.exception("恢复失败")
            self.memory.fatal = True
            self.memory.stop_reason = "恢复失败"
            return "finish"
        return "prepare"

    def _finish(self) -> None:
        return None

    def _summary(self, status: str) -> str:
        base = (
            f"升级城墙 {self.memory.upgrades} 段，花费金币 {self.memory.gold_spent}，"
            f"圣水 {self.memory.elixir_spent}"
        )
        if self.memory.complete:
            base += "；城墙已无可升级项"
        elif self.memory.threshold_wait:
            base += "；资源未达到升级阈值"
        elif self.remaining is not None:
            base += f"；剩余 {self.remaining} 段"
        else:
            base += "；剩余数量未知"
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
