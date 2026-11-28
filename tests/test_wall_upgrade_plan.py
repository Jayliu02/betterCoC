import unittest
from types import SimpleNamespace

from bettercoc.config import Config
from bettercoc.geometry import Rect
from bettercoc.tasks.wall_upgrade import WallMemory, WallUpgradeTask, plan_batch


class FakeLogger:
    def info(self, message, *args):
        return None

    def warning(self, message, *args):
        return None


class FakeContext:
    def __init__(self, wall_config=None):
        data = {"task": {"wall_upgrade": wall_config or {}}}
        self.config = Config.from_dict(data)
        self.logger = FakeLogger()
        self.taps = []
        self.clock = lambda: 100.0

    def tap(self, x, y):
        self.taps.append((x, y))

    def sleep(self, seconds):
        return None

    def should_stop(self):
        return False


class PlanBatchTest(unittest.TestCase):
    def test_capped_by_remaining(self):
        self.assertEqual(plan_batch(5, 30, 10, None), 5)

    def test_capped_by_batch_size(self):
        self.assertEqual(plan_batch(200, 30, 10, None), 10)

    def test_capped_by_affordable(self):
        self.assertEqual(plan_batch(200, 4, 10, None), 4)

    def test_unlimited_upgrades_is_not_capped(self):
        self.assertEqual(plan_batch(25, 30, 10, None), 10)
        self.assertEqual(plan_batch(25, 30, 0, None), 25)

    def test_upgrade_limit_is_applied(self):
        self.assertEqual(plan_batch(200, 30, 10, 3), 3)
        self.assertEqual(plan_batch(200, 30, 10, 0), 0)

    def test_unknown_remaining_is_conservative(self):
        self.assertEqual(plan_batch(None, 30, 10, None), 10)
        self.assertEqual(plan_batch(None, 30, 0, None, unknown_batch=7), 7)

    def test_remaining_zero_blocks_batch(self):
        self.assertEqual(plan_batch(0, 30, 10, None), 0)

    def test_absolute_batch_cap(self):
        self.assertEqual(plan_batch(500, 300, 0, None, max_batch=30), 30)


class SelectBatchTest(unittest.TestCase):
    def make_task(self, wall_config=None, gold=10_000_000, elixir=10_000_000):
        task = WallUpgradeTask()
        task.ctx = FakeContext(wall_config)
        task.memory = WallMemory(gold=gold, elixir=elixir)
        task._load_settings()
        task._begin(task.ctx)
        selected = []
        task._read_cost = lambda name, screen: (500_000, 1.0)
        task._select_batch = lambda count: selected.append(count)
        return task, selected

    def test_batch_is_capped_by_observed_remaining(self):
        task, selected = self.make_task()
        task.remaining = 5
        self.assertEqual(task._select(), "upgrade")
        self.assertEqual(selected, [5])
        self.assertEqual(task.memory.pending_batch, 5)
        self.assertEqual(task.memory.pending_currency, "gold")
        self.assertEqual(task.memory.pending_cost, 2_500_000)

    def test_unknown_remaining_uses_unknown_batch_size(self):
        task, selected = self.make_task(
            {"batch_size": 0, "unknown_batch_size": 7}
        )
        task.remaining = None
        self.assertEqual(task._select(), "upgrade")
        self.assertEqual(selected, [7])

    def test_upgrade_limit_caps_batch(self):
        task, selected = self.make_task()
        task.max_upgrades = 3
        task.remaining = 10
        self.assertEqual(task._select(), "upgrade")
        self.assertEqual(selected, [3])

    def test_insufficient_resources_finishes(self):
        task, selected = self.make_task(gold=100, elixir=100)
        task.remaining = 10
        self.assertEqual(task._select(), "finish")
        self.assertEqual(selected, [])

    def test_batch_is_capped_by_layout_limit(self):
        task, selected = self.make_task()
        task.remaining = 50
        self.assertEqual(task._select(), "upgrade")
        self.assertEqual(selected, [9])


class PreferredRowTest(unittest.TestCase):
    def setUp(self):
        self.task = WallUpgradeTask()

    def test_prefers_positive_count_over_zero_and_unknown(self):
        rows = [("a", 0), ("b", None), ("c", 5)]
        self.assertEqual(self.task._preferred_row(rows), ("c", 5))

    def test_takes_first_positive_row(self):
        rows = [("a", 3), ("b", 5)]
        self.assertEqual(self.task._preferred_row(rows), ("a", 3))

    def test_falls_back_to_unknown_row(self):
        rows = [("a", 0), ("b", None)]
        self.assertEqual(self.task._preferred_row(rows), ("b", None))

    def test_returns_none_when_all_rows_are_zero(self):
        self.assertIsNone(self.task._preferred_row([("a", 0), ("b", 0)]))

    def test_returns_none_without_rows(self):
        self.assertIsNone(self.task._preferred_row([]))

    def test_two_level_rows_continue_after_first_group(self):
        first = ("row14to15", 299)
        second = ("row15to16", 25)
        self.assertEqual(self.task._preferred_row([first, second]), first)
        self.assertEqual(self.task._preferred_row([("row14to15", 0), second]), second)
        self.assertIsNone(
            self.task._preferred_row([("row14to15", 0), ("row15to16", 0)])
        )


class FakeDigits:
    def __init__(self, values):
        self.values = list(values)

    def read(self, screen, roi):
        return self.values.pop(0), "text", 0.9


class ReadRowsTest(unittest.TestCase):
    def test_out_of_range_reading_is_treated_as_unknown(self):
        task = WallUpgradeTask()
        task.ctx = SimpleNamespace(
            vision=SimpleNamespace(digits=FakeDigits([855, 299])),
            logger=FakeLogger(),
        )
        task.remaining_offset = (115, -19, 120, 50)
        task.max_walls = 500
        rows = [
            SimpleNamespace(rect=Rect(1430, 85, 85, 65), name="wall_entry"),
            SimpleNamespace(rect=Rect(1430, 175, 85, 65), name="wall_entry"),
        ]
        result = task._read_rows(rows, screen=object())
        self.assertIsNone(result[0][1])
        self.assertEqual(result[1][1], 299)


class BatchContext:
    def __init__(self, panel_after_row=1, batch_after_more=1):
        self.panel_after_row = panel_after_row
        self.batch_after_more = batch_after_more
        self.row_taps = 0
        self.more_taps = 0
        self.panel = False
        self.batch = False
        self.taps = []
        assets = SimpleNamespace(
            has=lambda name: name in ("wall_batch_remove", "wall_more")
        )
        self.vision = SimpleNamespace(assets=assets)
        self.logger = FakeLogger()

    def screen(self):
        return object()

    def sleep(self, seconds):
        return None

    def tap(self, x, y):
        self.taps.append((x, y))
        if y == 439:
            self.row_taps += 1
            if self.row_taps >= self.panel_after_row:
                self.panel = True
            return
        if (x, y) == (925, 753):
            self.more_taps += 1
            if self.panel and self.more_taps >= self.batch_after_more:
                self.batch = True

    def find_optional(self, name, screen=None):
        if name == "wall_batch_remove":
            return object() if self.batch else None
        if name == "wall_more":
            return object() if self.panel and not self.batch else None
        if name in ("wall_add_1", "wall_add_10"):
            return None
        return None


class SettleCostsTest(unittest.TestCase):
    def make_task(self, gold, elixir):
        task = WallUpgradeTask()
        task.cost_per_wall = 600_000
        task._read_cost = lambda name, screen: (
            (gold, 0.9) if name == "wall_cost_gold" else (elixir, 0.9)
        )
        return task

    def test_valid_read_fills_missing_currency(self):
        task = self.make_task(1_200_000, None)
        self.assertEqual(task._settle_costs(None), (1_200_000, 1_200_000))

    def test_equal_reads_are_kept(self):
        task = self.make_task(1_200_000, 1_200_000)
        self.assertEqual(task._settle_costs(None), (1_200_000, 1_200_000))

    def test_falls_back_when_both_reads_fail(self):
        task = self.make_task(None, None)
        self.assertEqual(task._settle_costs(None), (600_000, 600_000))


class EnterBatchTest(unittest.TestCase):
    def make_task(self, ctx):
        task = WallUpgradeTask()
        task.more_point = (925, 753)
        task.ctx = ctx
        return task

    def test_label_anchor_taps_left_of_the_text(self):
        ctx = BatchContext()
        task = self.make_task(ctx)
        entry = SimpleNamespace(rect=Rect(1492, 422, 62, 34), name="wall_row_label")
        self.assertTrue(task._enter_batch(entry))
        self.assertEqual(ctx.taps[0], (1457, 439))
        self.assertEqual(ctx.taps[1], (925, 753))
        self.assertEqual(len(ctx.taps), 2)

    def test_retries_row_tap_when_panel_does_not_open(self):
        ctx = BatchContext(panel_after_row=2)
        task = self.make_task(ctx)
        entry = SimpleNamespace(rect=Rect(1492, 422, 62, 34), name="wall_row_label")
        self.assertTrue(task._enter_batch(entry))
        self.assertEqual(ctx.row_taps, 2)
        self.assertEqual(ctx.more_taps, 1)
        self.assertEqual(ctx.taps[:2], [(1457, 439), (1457, 439)])

    def test_retries_more_tap_while_panel_is_open(self):
        ctx = BatchContext(batch_after_more=2)
        task = self.make_task(ctx)
        entry = SimpleNamespace(rect=Rect(1492, 422, 62, 34), name="wall_row_label")
        self.assertTrue(task._enter_batch(entry))
        self.assertEqual(ctx.row_taps, 1)
        self.assertEqual(ctx.more_taps, 2)

    def test_returns_false_when_batch_never_opens(self):
        ctx = BatchContext(batch_after_more=99)
        task = self.make_task(ctx)
        entry = SimpleNamespace(rect=Rect(1492, 422, 62, 34), name="wall_row_label")
        self.assertFalse(task._enter_batch(entry))


if __name__ == "__main__":
    unittest.main()
