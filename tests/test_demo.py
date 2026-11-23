import unittest

from bettercoc.demo import run_demo

from support import make_temp_dir


class DemoLoopTest(unittest.TestCase):
    def test_demo_loop(self):
        root = make_temp_dir("demo")
        result = run_demo(root / "demo", cycles=2)
        self.assertEqual(result.result.status, "success", result.result.reason)
        self.assertEqual(result.result.counters.get("raids"), 2)
        self.assertEqual(result.result.counters.get("cycles"), 2)
        self.assertEqual(result.game.raids, 2)
        self.assertEqual(result.game.upgrades, 0)
        self.assertGreaterEqual(len(result.result.transitions), 5)
        self.assertTrue((result.root / "screens" / "home.png").exists())
        self.assertTrue((result.root / "screenshots").exists())


if __name__ == "__main__":
    unittest.main()
