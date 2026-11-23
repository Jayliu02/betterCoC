import unittest

from bettercoc.geometry import Rect, Viewport


class RectTest(unittest.TestCase):
    def test_parse_forms(self):
        self.assertEqual(Rect.from_value([1, 2, 3, 4]), Rect(1, 2, 3, 4))
        self.assertEqual(
            Rect.from_value({"x": 1, "y": 2, "width": 3, "height": 4}),
            Rect(1, 2, 3, 4),
        )
        self.assertEqual(Rect.from_value("1,2,3,4"), Rect(1, 2, 3, 4))

    def test_geometry(self):
        rect = Rect(10, 20, 100, 50)
        self.assertEqual(rect.right, 110)
        self.assertEqual(rect.bottom, 70)
        self.assertEqual(rect.center, (60, 45))
        self.assertTrue(rect.contains(10, 20))
        self.assertFalse(rect.contains(110, 20))

    def test_clamp_and_expand(self):
        self.assertEqual(Rect(-10, -10, 50, 50).clamp(100, 100), Rect(0, 0, 40, 40))
        self.assertEqual(Rect(90, 90, 50, 50).clamp(100, 100), Rect(90, 90, 10, 10))
        self.assertEqual(Rect(10, 10, 20, 20).expand(5), Rect(5, 5, 30, 30))

    def test_iou(self):
        self.assertAlmostEqual(Rect(0, 0, 10, 10).iou(Rect(0, 0, 10, 10)), 1.0)
        self.assertAlmostEqual(Rect(0, 0, 10, 10).iou(Rect(10, 0, 10, 10)), 0.0)
        self.assertAlmostEqual(Rect(0, 0, 10, 10).iou(Rect(5, 0, 10, 10)), 1 / 3)

    def test_viewport(self):
        viewport = Viewport(1280, 720)
        self.assertEqual(viewport.to_device(960, 540), (640, 360))
        self.assertEqual(viewport.to_canonical(640, 360), (960, 540))
        self.assertEqual(viewport.to_device(5000, 5000), (1279, 719))


if __name__ == "__main__":
    unittest.main()
