import unittest

from bettercoc.tasks.base import Task, TaskResult


class ClockContext:
    def __init__(self):
        self.now = 1000.0

    def clock(self):
        return self.now


class SampleTask(Task):
    name = "sample"

    def run(self, ctx):
        self._begin(ctx)
        return TaskResult(task=self.name, status="success", reason="")


class TaskTimingTest(unittest.TestCase):
    def test_runtime_starts_at_task_begin(self):
        ctx = ClockContext()
        task = SampleTask()
        task.run(ctx)
        ctx.now += 14 * 60
        self.assertFalse(task._runtime_exceeded(ctx, 15))
        ctx.now += 61
        self.assertTrue(task._runtime_exceeded(ctx, 15))

    def test_each_task_instance_starts_fresh(self):
        ctx = ClockContext()
        first = SampleTask()
        first.run(ctx)
        ctx.now += 30 * 60
        second = SampleTask()
        second.run(ctx)
        self.assertTrue(first._runtime_exceeded(ctx, 15))
        self.assertFalse(second._runtime_exceeded(ctx, 15))

    def test_zero_minutes_never_exceeds(self):
        ctx = ClockContext()
        task = SampleTask()
        task.run(ctx)
        ctx.now += 24 * 3600
        self.assertFalse(task._runtime_exceeded(ctx, 0))
        self.assertEqual(task._task_elapsed(ctx), 24 * 3600)


if __name__ == "__main__":
    unittest.main()
