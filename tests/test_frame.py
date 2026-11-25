import logging
import unittest
from pathlib import Path

import numpy as np

from bettercoc.baseline import build_vision_from_manifest, load_fixture_manifest
from bettercoc.capture import FolderCapture, StaticCapture
from bettercoc.config import Config
from bettercoc.context import Context
from bettercoc.demo import MockCapture, MockGame
from bettercoc.errors import CaptureError, FrameStaleError
from bettercoc.frame import FrameProvider
from bettercoc.geometry import Rect
from bettercoc.image import load_image

from support import make_temp_dir

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "baseline"


class FakeClock:
    def __init__(self, value: float = 1000.0) -> None:
        self.now = value

    def __call__(self) -> float:
        return self.now


class BrokenCapture:
    description = "broken"

    def grab(self):
        raise CaptureError("截图失败")

    def close(self):
        return None


def fixture_image(name: str):
    manifest = load_fixture_manifest(FIXTURES)
    frames = {frame["id"]: frame for frame in manifest["frames"]}
    return load_image(FIXTURES / frames[name]["file"])


class FrameProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = fixture_image("home-a")
        cls.scout = fixture_image("scout-a")
        cls.scaled = fixture_image("home-a-scale-1280x720")

    def test_static_identity_and_sequence(self):
        provider = FrameProvider(StaticCapture(self.home), source_id="static")
        first = provider.capture()
        second = provider.capture()
        self.assertEqual(first.sequence, 1)
        self.assertEqual(second.sequence, 2)
        self.assertNotEqual(first.frame_id, second.frame_id)
        self.assertEqual(first.source_id, "static")
        self.assertEqual(first.raw_size, (1920, 1080))
        self.assertEqual(first.canonical_size, (1920, 1080))
        self.assertIs(provider.peek(), second)

    def test_folder_capture_order(self):
        temp = make_temp_dir("frame-folder")
        from bettercoc.image import save_image

        save_image(temp / "01-home.png", self.home)
        save_image(temp / "02-scout.png", self.scout)
        provider = FrameProvider(FolderCapture(temp), source_id="folder")
        first = provider.capture()
        second = provider.capture()
        self.assertEqual(first.sequence, 1)
        self.assertEqual(second.sequence, 2)
        self.assertEqual(first.raw_size, (1920, 1080))
        self.assertGreater(float(np.mean(first.image)), 0.0)
        self.assertFalse(np.array_equal(first.image, second.image))

    def test_mock_capture_sequence(self):
        game = MockGame()
        provider = FrameProvider(MockCapture(game), source_id="mock")
        first = provider.capture()
        game.state = "attack_menu"
        second = provider.capture()
        self.assertEqual(second.sequence, 2)
        self.assertFalse(np.array_equal(first.image, second.image))
        self.assertEqual(game.seen_states, ["home", "attack_menu"])

    def test_scaled_frame_viewport_roundtrip(self):
        provider = FrameProvider(StaticCapture(self.scaled), source_id="scaled")
        frame = provider.capture()
        self.assertEqual(frame.raw_size, (1280, 720))
        self.assertEqual(frame.canonical_size, (1920, 1080))
        self.assertAlmostEqual(frame.viewport.scale_x, 1280 / 1920)
        for canonical_x, canonical_y in [
            (0, 0),
            (110, 935),
            (1832, 935),
            (1919, 1079),
        ]:
            device_x, device_y = frame.viewport.to_device(canonical_x, canonical_y)
            back_x, back_y = frame.viewport.to_canonical(device_x, device_y)
            self.assertLessEqual(abs(back_x - canonical_x), 2)
            self.assertLessEqual(abs(back_y - canonical_y), 2)

    def test_image_is_read_only(self):
        provider = FrameProvider(StaticCapture(self.home), source_id="static")
        frame = provider.capture()
        self.assertFalse(frame.image.flags.writeable)
        with self.assertRaises(ValueError):
            frame.image[0, 0, 0] = 1
        copy = frame.copy_image()
        self.assertTrue(copy.flags.writeable)
        copy[0, 0, 0] = 7

    def test_crop_on_frame(self):
        provider = FrameProvider(StaticCapture(self.home), source_id="static")
        frame = provider.capture()
        patch = frame.crop(Rect(1580, 20, 240, 70))
        self.assertEqual(patch.shape[0], 70)
        self.assertEqual(patch.shape[1], 240)
        self.assertEqual(frame.crop(Rect(-10, -10, 5, 5)).size, 0)

    def test_capture_failure_keeps_sequence(self):
        provider = FrameProvider(BrokenCapture(), source_id="broken")
        with self.assertRaises(CaptureError):
            provider.capture()
        self.assertEqual(provider.sequence, 0)
        self.assertIsNone(provider.peek())

    def test_age_and_stale(self):
        clock = FakeClock()
        provider = FrameProvider(
            StaticCapture(self.home), source_id="static", clock=clock, stale_after=1.5
        )
        frame = provider.capture()
        self.assertFalse(frame.is_stale(now=clock.now))
        clock.now += 1.6
        self.assertTrue(frame.is_stale(now=clock.now))
        self.assertAlmostEqual(frame.age(now=clock.now), 1.6)
        self.assertFalse(frame.is_stale(max_age=2.0, now=clock.now))


class ContextFrameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_fixture_manifest(FIXTURES)
        cls.vision = build_vision_from_manifest(cls.manifest)
        cls.home = fixture_image("home-a")

    def setUp(self):
        self.clock = FakeClock()
        self.logger = logging.getLogger("bettercoc.test.frame")
        self.logger.addHandler(logging.NullHandler())
        self.logger.propagate = False

    def _context(self, image=None):
        config = Config.from_dict({"runtime": {"dry_run": True}})
        return Context(
            config=config,
            vision=self.vision,
            capture=StaticCapture(image if image is not None else self.home),
            controller=None,
            logger=self.logger,
            canonical=(1920, 1080),
            dry_run=True,
            jitter=0,
            tap_delay=(0.0, 0.0),
            clock=self.clock,
            sleeper=lambda seconds: None,
            stale_after=2.0,
        )

    def test_screen_has_frame_identity(self):
        ctx = self._context()
        first = ctx.screen()
        second = ctx.screen()
        self.assertIsNotNone(first.frame_id)
        self.assertIsNotNone(second.frame_id)
        self.assertNotEqual(first.frame_id, second.frame_id)
        self.assertEqual(first.sequence, 1)
        self.assertEqual(second.sequence, 2)
        self.assertEqual(ctx.stats.get("captures"), 2)
        self.assertEqual(ctx.last_frame.frame_id, second.frame_id)

    def test_same_frame_recognition_shares_frame_id(self):
        ctx = self._context()
        screen = ctx.screen()
        hit = ctx.find("home_attack", screen=screen)
        miss = ctx.find("game_stop", screen=screen)
        self.assertIsNotNone(hit)
        self.assertIsNone(miss)
        self.assertEqual(hit.frame_id, screen.frame_id)
        self.assertEqual(ctx.stats.get("captures"), 1)

    def test_find_in_stale_frame_raises(self):
        ctx = self._context()
        frame = ctx.capture_frame()
        self.assertIsNotNone(ctx.find_in(frame, "home_attack"))
        self.clock.now += 5.0
        with self.assertRaises(FrameStaleError):
            ctx.find_in(frame, "home_attack")
        with self.assertRaises(FrameStaleError):
            ctx.find_all_in(frame, "home_attack")

    def test_current_frame_does_not_recapture(self):
        ctx = self._context()
        self.assertEqual(ctx.stats.get("captures"), 0)
        first = ctx.current_frame()
        second = ctx.current_frame()
        self.assertIs(first, second)
        self.assertEqual(ctx.stats.get("captures"), 1)
        refreshed = ctx.refresh_frame()
        self.assertNotEqual(refreshed.frame_id, first.frame_id)
        self.assertEqual(ctx.stats.get("captures"), 2)

    def test_frame_age_tracks_clock(self):
        ctx = self._context()
        self.assertIsNone(ctx.frame_age())
        ctx.capture_frame()
        self.clock.now += 0.5
        self.assertAlmostEqual(ctx.frame_age(), 0.5)

    def test_find_without_screen_captures_new_frame(self):
        ctx = self._context()
        ctx.find("home_attack")
        ctx.find("home_attack")
        self.assertEqual(ctx.stats.get("captures"), 2)


class FrameSerializationTest(unittest.TestCase):
    def test_to_dict_roundtrip(self):
        provider = FrameProvider(StaticCapture(fixture_image("home-a")), source_id="static")
        frame = provider.capture()
        data = frame.to_dict()
        self.assertEqual(data["frame_id"], frame.frame_id)
        self.assertEqual(data["raw_size"], [1920, 1080])
        self.assertEqual(data["canonical_size"], [1920, 1080])
        self.assertEqual(data["viewport"]["device_width"], 1920)
        self.assertEqual(data["sequence"], 1)


if __name__ == "__main__":
    unittest.main()
