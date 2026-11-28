import unittest
from types import SimpleNamespace

from bettercoc.config import Config
from bettercoc.result import Match
from bettercoc.tasks.raid import RaidMemory, RaidTask


class FakeLogger:
    def info(self, message, *args):
        return None

    def warning(self, message, *args):
        return None


class FakeStats:
    def __init__(self):
        self.values = {}

    def set(self, key, value):
        self.values[key] = value


class ChestContext:
    def __init__(self):
        self.taps = []
        self.logger = FakeLogger()
        self.stats = FakeStats()
        self.clock = lambda: 0.0
        self.tap_count = 0
        self.chest_taps = 0
        self.continue_visible = False
        assets = SimpleNamespace(
            has=lambda name: name
            in ("treasure_chest", "treasure_chest_hint", "chest_continue")
        )
        self.vision = SimpleNamespace(assets=assets)

    def screen(self):
        return object()

    def find_optional(self, name, screen=None):
        if name in ("treasure_chest", "treasure_chest_hint"):
            return object()
        if name == "chest_continue":
            return SimpleNamespace(center=(961, 932)) if self.continue_visible else None
        if name == "battle_return_home":
            return None
        return None

    def tap(self, x, y):
        self.taps.append((x, y))
        if (x, y) == (960, 540):
            self.chest_taps += 1
            if self.chest_taps >= 4:
                self.continue_visible = True

    def tap_match(self, match, offset=(0, 0)):
        self.taps.append(match.center)

    def sleep(self, seconds):
        return None

    def should_stop(self):
        return False


class ChestTest(unittest.TestCase):
    def make_task(self):
        task = RaidTask()
        task.ctx = ChestContext()
        task.memory = RaidMemory()
        task.chest_taps = 4
        task.chest_tap_delay = 0.0
        task.chest_wait = 0.0
        task.chest_continue_timeout = 10.0
        task.chest_point = (960, 540)
        task.chest_continue_point = (961, 932)
        return task

    def test_chest_is_visible(self):
        task = self.make_task()
        self.assertTrue(task._treasure_chest_visible())

    def test_chest_is_opened_with_four_taps_then_continue(self):
        task = self.make_task()
        task._open_treasure_chest()
        self.assertEqual(task.ctx.chest_taps, 4)
        self.assertEqual(task.ctx.taps[:4], [(960, 540)] * 4)
        self.assertEqual(task.ctx.taps[-1], (961, 932))
        self.assertEqual(task.memory.chests, 1)
        self.assertEqual(task.ctx.stats.values["chests"], 1)


class LootContext:
    def __init__(self, values):
        self.values = values
        self.logger = FakeLogger()
        self.config = Config.from_dict({"task": {"raid": {}}})
        self.vision = SimpleNamespace(assets=SimpleNamespace(has=lambda name: True))

    def screen(self):
        return object()

    def find(self, asset, screen=None):
        label = {
            "loot_gold": "gold",
            "loot_elixir": "elixir",
            "loot_dark": "dark",
        }[asset]
        value = self.values.get(label)
        if value is None:
            return None
        return Match(rect=None, score=1.0, text=str(value), name=asset)


class LootTest(unittest.TestCase):
    def make_task(self, values, min_total):
        task = RaidTask()
        task.ctx = LootContext(values)
        task.min_total = min_total
        task.max_next = 5
        task.min_gold = 0
        task.min_elixir = 0
        task.min_dark = 0
        task._loot_warned = False
        return task

    def test_total_at_one_million_passes(self):
        task = self.make_task({"gold": 600_000, "elixir": 400_000}, 1_000_000)
        self.assertTrue(task._loot_enough())

    def test_total_below_one_million_is_rejected(self):
        task = self.make_task({"gold": 500_000, "elixir": 400_000}, 1_000_000)
        self.assertFalse(task._loot_enough())

    def test_default_threshold_is_one_million(self):
        task = RaidTask()
        task.ctx = LootContext({"gold": 600_000, "elixir": 400_000})
        task._load_settings()
        self.assertEqual(task.min_total, 1_000_000)
        self.assertTrue(task._loot_enough())


if __name__ == "__main__":
    unittest.main()
