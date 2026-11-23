import unittest

import numpy as np

from bettercoc.geometry import Rect
from bettercoc.image import normalize_frame, save_image, load_image

from support import make_temp_dir


class ImageTest(unittest.TestCase):
    def test_normalize(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        screen = normalize_frame(frame, (1920, 1080))
        self.assertEqual(screen.image.shape, (1080, 1920, 3))
        self.assertEqual(screen.viewport.device_width, 1280)
        self.assertEqual(screen.viewport.device_height, 720)
        self.assertAlmostEqual(screen.viewport.scale_x, 2 / 3)
        self.assertAlmostEqual(screen.viewport.scale_y, 2 / 3)

    def test_crop(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[100:200, 300:500] = 255
        screen = normalize_frame(frame, (1920, 1080))
        crop = screen.crop(Rect(300, 100, 200, 100))
        self.assertEqual(crop.shape, (100, 200, 3))
        self.assertTrue((crop == 255).all())

    def test_roundtrip(self):
        root = make_temp_dir("image")
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[10:20, 20:30] = (1, 2, 3)
        path = root / "shot.png"
        save_image(path, frame)
        loaded = load_image(path)
        self.assertEqual(loaded.shape, frame.shape)
        self.assertTrue((loaded == frame).all())


if __name__ == "__main__":
    unittest.main()
