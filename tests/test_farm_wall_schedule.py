import unittest

from bettercoc.tasks.farm_wall import FarmMemory, FarmWallTask


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append(("info", message % args if args else message))

    def warning(self, message, *args):
        self.messages.append(("warning", message % args if args else message))


class FakeContext:
    def __init__(self):
        self.logger = FakeLogger()


class FarmWallScheduleTest(unittest.TestCase):
    def make_task(self, state, calls, threshold=100):
        def upgrade():
            calls.append("upgrade")
            state["walls"] = max(0, state["walls"] - 1)
            return 1

        def raid():
            calls.append("raid")
            state["gold"] += 30
            return 1

        task = FarmWallTask()
        task.ctx = FakeContext()
        task.memory = FarmMemory()
        task.threshold_ratio = 0.9
        task.last_wall_remaining = state["walls"]
        task._threshold = lambda: threshold
        task._walls_done = lambda: state["walls"] <= 0
        task._read_resources = lambda: (state["gold"], state["elixir"], 0)
        task._upgrade_walls = upgrade
        task._raid_once = raid
        task._limits_reached = lambda: len(calls) > 10
        return task

    def test_over_threshold_upgrades_before_raid(self):
        state = {"gold": 105, "elixir": 0, "walls": 2}
        calls = []
        task = self.make_task(state, calls)
        task._schedule()
        self.assertEqual(calls, ["upgrade", "raid", "upgrade"])

    def test_under_threshold_raids_before_upgrade(self):
        state = {"gold": 50, "elixir": 0, "walls": 2}
        calls = []
        task = self.make_task(state, calls)
        task._schedule()
        self.assertEqual(calls, ["raid", "upgrade", "raid", "upgrade"])

    def test_over_threshold_and_walls_done_exits(self):
        state = {"gold": 105, "elixir": 0, "walls": 0}
        calls = []
        task = self.make_task(state, calls)
        task._schedule()
        self.assertEqual(calls, [])

    def test_walls_done_still_farms_to_threshold(self):
        state = {"gold": 0, "elixir": 0, "walls": 0}
        calls = []
        task = self.make_task(state, calls)
        task._schedule()
        self.assertEqual(calls, ["raid", "upgrade", "raid", "raid", "raid"])
        self.assertGreater(state["gold"], 100)


if __name__ == "__main__":
    unittest.main()
