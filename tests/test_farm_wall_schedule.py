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
        task = FarmWallTask()

        def upgrade():
            calls.append("upgrade")
            state["walls"] = max(0, state["walls"] - 1)
            if state["walls"] <= 0:
                task.walls_complete = True
            return 1

        def raid():
            calls.append("raid")
            state["gold"] += 30
            return 1

        task.ctx = FakeContext()
        task.memory = FarmMemory()
        task.threshold_ratio = 0.9
        task.wall_remaining = state["walls"]
        task.walls_complete = False
        task.farm_after_complete = False
        task._threshold = lambda: threshold
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
        self.assertTrue(task.walls_complete)

    def test_under_threshold_raids_before_upgrade(self):
        state = {"gold": 50, "elixir": 0, "walls": 2}
        calls = []
        task = self.make_task(state, calls)
        task._schedule()
        self.assertEqual(
            calls, ["raid", "raid", "upgrade", "raid", "upgrade"]
        )

    def test_completion_comes_from_observation_not_state(self):
        state = {"gold": 105, "elixir": 0, "walls": 0}
        calls = []
        task = self.make_task(state, calls)
        task.wall_remaining = 0
        task._schedule()
        self.assertEqual(calls, ["upgrade"])
        self.assertTrue(task.walls_complete)

    def test_complete_state_stops_without_farming_to_threshold(self):
        state = {"gold": 0, "elixir": 0, "walls": 0}
        calls = []
        task = self.make_task(state, calls)
        task.walls_complete = True
        task._schedule()
        self.assertEqual(calls, [])

    def test_farm_after_complete_runs_threshold_loop(self):
        state = {"gold": 0, "elixir": 0, "walls": 0}
        calls = []
        task = self.make_task(state, calls)
        task.walls_complete = True
        task.farm_after_complete = True
        farmed = []
        task._farm_to_threshold = lambda: farmed.append("farm")
        task._schedule()
        self.assertEqual(calls, [])
        self.assertEqual(farmed, ["farm"])


if __name__ == "__main__":
    unittest.main()
