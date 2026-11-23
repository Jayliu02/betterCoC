import logging
import unittest

from bettercoc.errors import StopRequested, TaskError
from bettercoc.state_machine import StateMachine


def quiet_logger():
    logger = logging.getLogger("bettercoc.test.state")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    logger.setLevel(logging.CRITICAL)
    return logger


class StateMachineTest(unittest.TestCase):
    def test_linear_flow(self):
        machine = StateMachine(quiet_logger())
        machine.add("start", lambda: "middle")
        machine.add("middle", lambda: "end")
        machine.add("end", lambda: None)
        final = machine.run("start")
        self.assertEqual(final, "end")
        self.assertEqual(
            [(item.source, item.target) for item in machine.transitions],
            [("start", "middle"), ("middle", "end")],
        )

    def test_error_recovery(self):
        machine = StateMachine(quiet_logger())
        calls = {"count": 0}
        recovered = []

        def flaky():
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("boom")
            return "finish"

        def recover():
            recovered.append(True)
            return "flaky"

        machine.add("start", lambda: "flaky")
        machine.add("flaky", flaky, on_error="recover")
        machine.add("recover", recover)
        machine.add("finish", lambda: None)
        self.assertEqual(machine.run("start"), "finish")
        self.assertEqual(recovered, [True])
        self.assertIsInstance(machine.last_error, RuntimeError)

    def test_unknown_transition(self):
        machine = StateMachine(quiet_logger())
        machine.add("start", lambda: "missing")
        with self.assertRaises(TaskError):
            machine.run("start")

    def test_step_limit(self):
        machine = StateMachine(quiet_logger())
        machine.add("loop", lambda: "loop")
        with self.assertRaises(TaskError):
            machine.run("loop", max_steps=5)

    def test_stop_propagates(self):
        machine = StateMachine(quiet_logger())

        def stop():
            raise StopRequested("stop")

        machine.add("start", stop, on_error="recover")
        machine.add("recover", lambda: "finish")
        machine.add("finish", lambda: None)
        with self.assertRaises(StopRequested):
            machine.run("start")


if __name__ == "__main__":
    unittest.main()
