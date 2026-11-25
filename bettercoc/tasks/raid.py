from __future__ import annotations

from dataclasses import dataclass

from ..context import Context
from ..errors import MissingAssetError, OcrUnavailable, StopRequested, TaskError
from ..ocr import parse_number
from ..recovery import ensure_home, reload_if_stopped
from ..state_machine import StateMachine
from .base import Task, TaskResult

HOME_ATTACK = "home_attack"
ATTACK_MULTIPLAYER = "attack_multiplayer"
ATTACK_FIND_MATCH = "attack_find_match"
ARMY_ATTACK = "army_attack"
SCOUT_NEXT = "scout_next"
SCOUT_ATTACK = "scout_attack"
AUTO_BATTLE = "auto_battle"
BATTLE_END = "battle_end"
BATTLE_RETURN = "battle_return_home"
DIALOG_OK = "dialog_ok"
LOOT_GOLD = "loot_gold"
LOOT_ELIXIR = "loot_elixir"
LOOT_DARK = "loot_dark"


@dataclass
class RaidMemory:
    cycles: int = 0
    raids: int = 0
    errors: int = 0
    fatal: bool = False


class RaidTask(Task):
    name = "raid"

    def __init__(self, max_cycles: int | None = None) -> None:
        self._max_cycles_override = max_cycles

    def run(self, ctx: Context) -> TaskResult:
        self.ctx = ctx
        self._begin(ctx)
        self.memory = RaidMemory()
        self._load_settings()
        machine = StateMachine(ctx.logger)
        machine.add("prepare", self._prepare, on_error="recover")
        machine.add("raid", self._raid, on_error="recover")
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
            reason = self._summary(status)
        except StopRequested as exc:
            status = "stopped"
            reason = self._summary("stopped")
            ctx.logger.info("任务停止: %s", exc)
        except Exception:
            try:
                ctx.save_screenshot("raid-error")
            except Exception:
                ctx.logger.exception("保存错误截图失败")
            raise
        finally:
            ctx.stats.set("raids", self.memory.raids)
            ctx.stats.set("cycles", self.memory.cycles)
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
        self.max_cycles = int(cfg.get("task.raid.max_cycles", 20))
        if self._max_cycles_override is not None:
            self.max_cycles = self._max_cycles_override
        self.max_runtime_min = float(cfg.get("task.raid.max_runtime_min", 60))
        self.max_errors = int(cfg.get("task.raid.max_errors", 3))
        self.match_timeout = float(cfg.get("task.raid.match_timeout", 45))
        self.battle_start_timeout = float(cfg.get("task.raid.battle_start_timeout", 45))
        self.battle_timeout = float(cfg.get("task.raid.battle_timeout", 240))
        self.result_timeout = float(cfg.get("task.raid.result_timeout", 20))
        self.end_battle_after_deploy = bool(
            cfg.get("task.raid.end_battle_after_deploy", True)
        )
        self.loot_check = bool(cfg.get("task.raid.loot_check", True))
        self.min_total = int(cfg.get("task.raid.min_total", 2_000_000))
        self.max_next = int(cfg.get("task.raid.max_next", 15))
        self.min_gold = int(cfg.get("task.raid.min_gold", 0))
        self.min_elixir = int(cfg.get("task.raid.min_elixir", 0))
        self.min_dark = int(cfg.get("task.raid.min_dark", 0))
        self.auto_battle = bool(cfg.get("task.raid.auto_battle", True))
        self.troop_slots = self._points(
            cfg.get("task.raid.army.troop_slots", []), "task.raid.army.troop_slots"
        )
        self.deploy_points = self._points(
            cfg.get("task.raid.army.deploy_points", []), "task.raid.army.deploy_points"
        )
        self.waves = int(cfg.get("task.raid.army.waves", 1))
        self.deploy_delay = (
            float(cfg.get("task.raid.army.tap_delay_ms", 120)) / 1000.0
        )
        self._loot_warned = False

    def _points(self, raw, name: str) -> list[tuple[int, int]]:
        points: list[tuple[int, int]] = []
        if not isinstance(raw, list):
            raise TaskError(f"{name} 必须是坐标列表")
        for index, item in enumerate(raw):
            try:
                if isinstance(item, dict):
                    x, y = int(item["x"]), int(item["y"])
                else:
                    x, y = int(item[0]), int(item[1])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise TaskError(f"{name}[{index}] 坐标格式错误: {item!r}") from exc
            points.append((x, y))
        return points

    def _prepare(self) -> str:
        self._ensure_home()
        return "raid"

    def _ensure_home(self) -> None:
        ensure_home(self.ctx)

    def _raid(self) -> str:
        ctx = self.ctx
        self._ensure_home()
        ctx.logger.info("开始搜索对手")
        ctx.click(HOME_ATTACK, timeout=6)
        if ctx.vision.assets.has(ATTACK_MULTIPLAYER):
            ctx.click_if_present(ATTACK_MULTIPLAYER, timeout=2.0)
        ctx.click(ATTACK_FIND_MATCH, timeout=10)
        if ctx.vision.assets.has(ARMY_ATTACK):
            army = ctx.try_wait(ARMY_ATTACK, 5)
            if army is not None:
                ctx.logger.info("确认军队并开始搜索")
                ctx.tap_match(army)
        ctx.wait(SCOUT_NEXT, timeout=self.match_timeout)
        if not self._maybe_next():
            ctx.logger.warning("连续 %d 个对手资源不足，取消本次进攻", self.max_next)
            self._cancel_scout()
            return "decide"
        if self.auto_battle and ctx.vision.assets.has(AUTO_BATTLE):
            ctx.logger.info("使用自动战斗")
            auto = ctx.try_wait(AUTO_BATTLE, timeout=8, interval=0.4)
            if auto is None:
                ctx.logger.error("侦察界面没有自动战斗按钮，结束本次侦察")
                self._cancel_scout()
                raise TaskError(
                    "自动战斗不可用：侦察界面没有 auto_battle 按钮。"
                    "请在游戏内确认自动战斗是否开启，"
                    "或在 config 里配置手动下兵坐标（troop_slots / deploy_points）。"
                )
            ctx.tap_match(auto)
            self._wait_battle_result(self.battle_timeout)
            self.memory.raids += 1
            ctx.logger.info("第 %d 次进攻结束", self.memory.raids)
            return "decide"
        ctx.click(SCOUT_ATTACK, timeout=15)
        ctx.wait(BATTLE_END, timeout=self.battle_start_timeout)
        ctx.sleep(0.8)
        self._deploy()
        if self.end_battle_after_deploy:
            ctx.sleep(1.0)
            end = ctx.try_wait(BATTLE_END, 3)
            if end is not None:
                ctx.tap_match(end)
        timeout = self.result_timeout if self.end_battle_after_deploy else self.battle_timeout
        self._wait_battle_result(timeout)
        self.memory.raids += 1
        ctx.logger.info("第 %d 次进攻结束", self.memory.raids)
        return "decide"

    def _cancel_scout(self) -> None:
        ctx = self.ctx
        ctx.logger.info("结束当前侦察并回到主界面")
        self._ensure_home()

    def _maybe_next(self) -> bool:
        if not self.loot_check:
            return True
        ctx = self.ctx
        if self._loot_enough():
            return True
        for _ in range(max(0, self.max_next)):
            next_button = ctx.try_wait(SCOUT_NEXT, 3)
            if next_button is None:
                return False
            ctx.logger.info("资源不足，换下一个对手")
            ctx.tap_match(next_button)
            ctx.sleep(1.2)
            if ctx.try_wait(SCOUT_NEXT, self.match_timeout) is None:
                return False
            if self._loot_enough():
                return True
        return False

    def _loot_enough(self, screen=None) -> bool:
        ctx = self.ctx
        screen = screen or ctx.screen()
        checks = (
            ("gold", LOOT_GOLD, self.min_gold),
            ("elixir", LOOT_ELIXIR, self.min_elixir),
            ("dark", LOOT_DARK, self.min_dark),
        )
        values: dict[str, int] = {}
        for label, asset, minimum in checks:
            if not ctx.vision.assets.has(asset):
                continue
            try:
                match = ctx.find(asset, screen=screen)
            except (OcrUnavailable, MissingAssetError):
                if not self._loot_warned:
                    self._loot_warned = True
                    ctx.logger.warning("资源识别不可用，无法筛选对手")
                return False
            value = parse_number(match.text if match else None)
            if value is not None:
                values[label] = value
        if not values:
            if not self._loot_warned:
                self._loot_warned = True
                ctx.logger.warning("无法读取对手资源，拒绝进攻")
            return False
        total = values.get("gold", 0) + values.get("elixir", 0)
        enough = True
        if self.min_total > 0 and total < self.min_total:
            enough = False
        for label, _, minimum in checks:
            if minimum > 0 and values.get(label, 0) < minimum:
                enough = False
        ctx.logger.info(
            "对手资源 %s，合计 %d，筛选结果 %s",
            values,
            total,
            "通过" if enough else "不通过",
        )
        return enough

    def _deploy(self) -> None:
        ctx = self.ctx
        if not self.troop_slots or not self.deploy_points:
            ctx.logger.warning("未配置兵种或下兵坐标，跳过部署")
            return
        for wave in range(max(1, self.waves)):
            ctx.logger.info("部署第 %d/%d 波", wave + 1, max(1, self.waves))
            for slot in self.troop_slots:
                ctx.tap(*slot)
                ctx.sleep(self.deploy_delay)
                for point in self.deploy_points:
                    if ctx.should_stop():
                        raise StopRequested("已请求停止")
                    ctx.tap(*point)
                    ctx.sleep(self.deploy_delay)

    def _wait_battle_result(self, timeout: float) -> None:
        ctx = self.ctx
        deadline = ctx.clock() + timeout
        next_stop_check = 0.0
        while ctx.clock() < deadline:
            if ctx.should_stop():
                raise StopRequested("已请求停止")
            now = ctx.clock()
            if now >= next_stop_check:
                next_stop_check = now + 5.0
                if reload_if_stopped(ctx):
                    continue
            returned = ctx.try_wait(BATTLE_RETURN, 1.5)
            if returned is not None:
                ctx.tap_match(returned)
                ctx.sleep(1.8)
                continue
            if ctx.find(HOME_ATTACK) is not None:
                return
            ok = ctx.try_wait(DIALOG_OK, 0.5) if ctx.vision.assets.has(DIALOG_OK) else None
            if ok is not None:
                ctx.tap_match(ok)
                ctx.sleep(0.5)
                continue
            ctx.sleep(0.4)
        raise TaskError(f"等待战斗结算超时 ({timeout:g}s)")

    def _decide(self) -> str:
        ctx = self.ctx
        self.memory.cycles += 1
        if ctx.should_stop():
            return "finish"
        if self.max_cycles > 0 and self.memory.cycles >= self.max_cycles:
            ctx.logger.info("达到循环上限 %d", self.max_cycles)
            return "finish"
        if self._runtime_exceeded(ctx, self.max_runtime_min):
            ctx.logger.info("达到最大运行时间 %.0f 分钟", self.max_runtime_min)
            return "finish"
        return "raid"

    def _recover(self) -> str:
        ctx = self.ctx
        self.memory.errors += 1
        ctx.stats.incr("recoveries")
        if self.memory.errors > self.max_errors:
            ctx.logger.error("恢复次数超过上限 %d，任务结束", self.max_errors)
            self.memory.fatal = True
            return "finish"
        ctx.logger.warning("执行恢复流程 (%d/%d)", self.memory.errors, self.max_errors)
        try:
            self._ensure_home()
        except StopRequested:
            raise
        except Exception:
            ctx.logger.exception("恢复失败")
            self.memory.fatal = True
            return "finish"
        return "decide"

    def _finish(self) -> None:
        return None

    def _summary(self, status: str) -> str:
        base = f"{self.memory.cycles} 轮，进攻 {self.memory.raids} 次"
        if self.memory.errors:
            base += f"，恢复 {self.memory.errors} 次"
        if status == "stopped":
            return base + "，已停止"
        if status == "failed":
            return base + "，失败"
        return base
