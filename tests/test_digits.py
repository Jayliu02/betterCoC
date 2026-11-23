import unittest

import cv2
import numpy as np

from bettercoc.digits import DigitReader, normalize_glyph
from bettercoc.geometry import Rect
from bettercoc.image import normalize_frame


class DigitReaderTest(unittest.TestCase):
    def setUp(self):
        self.reader = DigitReader("assets/digits")

    def test_templates_available(self):
        self.assertTrue(self.reader.available())

    def test_normalize_shape(self):
        glyph = np.zeros((20, 10), dtype=np.uint8)
        glyph[5:15, 2:8] = 255
        normalized = normalize_glyph(glyph)
        self.assertEqual(normalized.shape, (32, 24))

    def test_read_synthetic_number(self):
        canvas = np.zeros((120, 400, 3), dtype=np.uint8)
        x = 20
        for digit in "914447":
            template = self.reader.templates[digit][0]
            canvas[40:72, x : x + 24] = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)
            x += 40
        screen = normalize_frame(canvas, (400, 120))
        value, text, score = self.reader.read(screen, Rect(0, 0, 400, 120))
        self.assertEqual(value, 914447)
        self.assertEqual(text, "914447")
        self.assertGreater(score, 0.9)


if __name__ == "__main__":
    unittest.main()
