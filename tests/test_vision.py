import unittest

import cv2
import numpy as np

from bettercoc.color import find_color
from bettercoc.geometry import Rect
from bettercoc.image import normalize_frame
from bettercoc.result import Match
from bettercoc.spec import Kind, Recognition
from bettercoc.template import Template, build_mask, find_template


def random_scene(width=640, height=480, seed=3):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (height, width, 3), dtype=np.uint8)


def screen_of(image):
    return normalize_frame(image, (image.shape[1], image.shape[0]))


def pattern(size=48, seed=9):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (size, size, 3), dtype=np.uint8)


class TemplateMatchTest(unittest.TestCase):
    def test_exact_match(self):
        scene = random_scene()
        tile = pattern()
        scene[120:168, 200:248] = tile
        spec = Recognition(name="tile", file="tile.png", threshold=0.99, grayscale=False)
        found = find_template(screen_of(scene), Template("tile", tile), spec)
        self.assertEqual(len(found), 1)
        self.assertGreaterEqual(found[0].score, 0.99)
        self.assertEqual(found[0].rect, Rect(200, 120, 48, 48))

    def test_roi_limits_search(self):
        scene = random_scene()
        tile = pattern()
        scene[300:348, 400:448] = tile
        spec = Recognition(
            name="tile",
            file="tile.png",
            roi=Rect(0, 0, 300, 300),
            threshold=0.99,
            grayscale=False,
        )
        found = find_template(screen_of(scene), Template("tile", tile), spec)
        self.assertEqual(found, [])

    def test_find_all_nms(self):
        scene = random_scene(800, 400)
        tile = pattern()
        scene[50:98, 50:98] = tile
        scene[50:98, 500:548] = tile
        spec = Recognition(name="tile", file="tile.png", threshold=0.95, grayscale=False)
        found = find_template(screen_of(scene), Template("tile", tile), spec, limit=5)
        self.assertEqual(len(found), 2)
        self.assertEqual({item.rect.x for item in found}, {50, 500})

    def test_multiscale(self):
        scene = random_scene(640, 480)
        tile = pattern(40)
        small = cv2.resize(tile, (32, 32), interpolation=cv2.INTER_AREA)
        scene[150:182, 200:232] = small
        spec = Recognition(
            name="tile",
            file="tile.png",
            threshold=0.7,
            grayscale=False,
            scales=(0.8,),
        )
        found = find_template(screen_of(scene), Template("tile", tile), spec)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].rect.width, 32)

    def test_mask_color(self):
        scene = random_scene()
        tile = np.zeros((60, 60, 3), dtype=np.uint8)
        tile[:, :] = (255, 0, 0)
        tile[10:50, 10:50] = (0, 0, 255)
        scene[100:160, 100:160] = tile
        scene[100:160, 100:110] = (0, 255, 0)
        bgr, mask = build_mask(tile, True, (255, 0, 0), 10)
        self.assertIsNotNone(mask)
        masked_spec = Recognition(
            name="tile",
            file="tile.png",
            threshold=0.95,
            grayscale=False,
            mask_color=(255, 0, 0),
        )
        found = find_template(screen_of(scene), Template("tile", bgr, mask), masked_spec)
        self.assertEqual(len(found), 1)
        plain_spec = Recognition(
            name="tile", file="tile.png", threshold=0.995, grayscale=False
        )
        plain = find_template(screen_of(scene), Template("tile", tile), plain_spec)
        self.assertEqual(plain, [])


class PointMatchTest(unittest.TestCase):
    def test_point_without_check_always_hits(self):
        from bettercoc.vision import Vision

        vision = Vision(assets=None)
        spec = Recognition(name="tap", kind=Kind.POINT, point=(110, 935))
        found = vision.find_all(screen_of(random_scene(100, 100)), spec)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].rect, Rect(110, 935, 1, 1))
        self.assertEqual(found[0].score, 1.0)

    def test_point_check(self):
        from bettercoc.spec import PointCheck
        from bettercoc.vision import Vision

        vision = Vision(assets=None)
        spec = Recognition(
            name="tap",
            kind=Kind.POINT,
            point=(50, 60),
            check=PointCheck(Rect(10, 10, 20, 20), ((41, 157, 207),), 25),
        )
        matching = np.zeros((100, 100, 3), dtype=np.uint8)
        matching[:, :] = (41, 157, 207)
        self.assertEqual(len(vision.find_all(screen_of(matching), spec)), 1)
        dimmed = np.zeros((100, 100, 3), dtype=np.uint8)
        dimmed[:, :] = (20, 78, 104)
        self.assertEqual(vision.find_all(screen_of(dimmed), spec), [])
        multiple = Recognition(
            name="tap",
            kind=Kind.POINT,
            point=(50, 60),
            check=PointCheck(
                Rect(10, 10, 20, 20),
                ((41, 157, 207), (20, 78, 104)),
                25,
            ),
        )
        self.assertEqual(len(vision.find_all(screen_of(dimmed), multiple)), 1)


class ColorMatchTest(unittest.TestCase):
    def test_green_button(self):
        scene = np.zeros((300, 300, 3), dtype=np.uint8)
        cv2.rectangle(scene, (80, 80), (220, 160), (0, 200, 0), -1)
        spec = Recognition(
            name="green",
            kind=Kind.COLOR,
            space="hsv",
            lower=(45, 100, 100),
            upper=(75, 255, 255),
            min_area=200,
            min_ratio=0.01,
        )
        found = find_color(screen_of(scene), spec)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].rect, Rect(80, 80, 141, 81))

    def test_wrong_color(self):
        scene = np.zeros((300, 300, 3), dtype=np.uint8)
        cv2.rectangle(scene, (80, 80), (220, 160), (200, 20, 20), -1)
        spec = Recognition(
            name="green",
            kind=Kind.COLOR,
            lower=(45, 100, 100),
            upper=(75, 255, 255),
            min_area=200,
            min_ratio=0.01,
        )
        self.assertEqual(find_color(screen_of(scene), spec), [])


class NumberParseTest(unittest.TestCase):
    def test_parse(self):
        from bettercoc.ocr import parse_number

        self.assertEqual(parse_number("1.2M"), 1_200_000)
        self.assertEqual(parse_number("350K"), 350_000)
        self.assertEqual(parse_number("1,234"), 1234)
        self.assertEqual(parse_number("12.3万"), 123_000)
        self.assertEqual(parse_number("2亿"), 200_000_000)
        self.assertEqual(parse_number("Gold 450,000"), 450_000)
        self.assertIsNone(parse_number("none"))
        self.assertIsNone(parse_number(None))


class TextFilterTest(unittest.TestCase):
    def test_filters(self):
        from bettercoc.ocr import filter_text

        matches = [
            Match(rect=Rect(0, 0, 10, 10), text="Find a Match", score=0.9),
            Match(rect=Rect(0, 10, 10, 10), text="Next", score=0.8),
        ]
        spec = Recognition(name="ocr", kind=Kind.OCR, text_any=("match",))
        self.assertEqual(len(filter_text(matches, spec)), 1)
        spec = Recognition(name="ocr", kind=Kind.OCR, text_all=("find", "match"))
        self.assertEqual(len(filter_text(matches, spec)), 1)
        spec = Recognition(name="ocr", kind=Kind.OCR, regex=r"^N")
        self.assertEqual(len(filter_text(matches, spec)), 1)


if __name__ == "__main__":
    unittest.main()
