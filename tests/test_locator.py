import unittest

from bettercoc.geometry import Rect
from bettercoc.locator import Locator
from bettercoc.result import Match


class FakeContext:
    def __init__(self, match):
        self.match = match
        self.tapped = None
        self.find_calls = 0
        self.wait_calls = 0

    def find(self, target, roi=None):
        self.find_calls += 1
        return self.match

    def find_all(self, target, roi=None, limit=10):
        return [self.match] if self.match else []

    def wait(self, target, timeout=10, interval=0.3, roi=None):
        self.wait_calls += 1
        return self.match

    def try_wait(self, target, timeout=3, interval=0.3, roi=None):
        return self.match

    def wait_gone(self, target, timeout=10, interval=0.3, roi=None):
        return None

    def tap_match(self, match):
        self.tapped = match


class LocatorTest(unittest.TestCase):
    def setUp(self):
        self.match = Match(rect=Rect(10, 20, 30, 40), score=0.9, name="btn")
        self.ctx = FakeContext(self.match)

    def test_find_and_exists(self):
        locator = Locator(self.ctx, "btn")
        self.assertTrue(locator.exists())
        self.assertEqual(locator.find(), self.match)
        self.assertEqual(locator.find_all(), [self.match])

    def test_click(self):
        locator = Locator(self.ctx, "btn", timeout=2)
        match = locator.click()
        self.assertEqual(match, self.match)
        self.assertEqual(self.ctx.tapped, self.match)
        self.assertEqual(self.ctx.wait_calls, 1)

    def test_builder(self):
        locator = Locator(self.ctx, "btn").with_timeout(1.5).with_roi(Rect(0, 0, 100, 100))
        self.assertEqual(locator.timeout, 1.5)
        self.assertEqual(locator.roi, Rect(0, 0, 100, 100))

    def test_missing(self):
        ctx = FakeContext(None)
        locator = Locator(ctx, "btn")
        self.assertFalse(locator.exists())
        self.assertIsNone(locator.click_if_exists())


if __name__ == "__main__":
    unittest.main()
