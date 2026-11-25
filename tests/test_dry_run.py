import logging
import unittest
from pathlib import Path

from bettercoc.baseline import build_vision_from_manifest, load_fixture_manifest
from bettercoc.capture import StaticCapture
from bettercoc.config import Config
from bettercoc.context import Context
from bettercoc.errors import TaskError
from bettercoc.image import load_image
from bettercoc.recovery import reload_if_stopped, restart_game
from bettercoc.resources import _zoom_out_min

from support import make_temp_dir

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "baseline"


class StrictController:
    def __init__(self):
        self.calls = []

    def _record(self, name, *args):
        self.calls.append((name, *args))
        raise AssertionError(f"dry-run 不应调用控制器: {name}")

    def tap(self, x, y):
        self._record("tap", x, y)

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self._record("swipe", x1, y1, x2, y2, duration_ms)

    def key(self, code):
        self._record("key", code)

    def scroll(self, x, y, vertical):
        self._record("scroll", x, y, vertical)

    def pinch(self, *args, **kwargs):
        self._record("pinch", *args)

    def force_stop(self, package):
        self._record("force_stop", package)

    def start_app(self, package):
        self._record("start_app", package)


class DryRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_fixture_manifest(FIXTURES)
        cls.vision = build_vision_from_manifest(cls.manifest)
        base = Path(cls.manifest["_dir"])
        frames = {frame["id"]: frame for frame in cls.manifest["frames"]}
        cls.home_image = load_image(base / frames["home-a"]["file"])
        cls.dialog_image = load_image(base / frames["disconnected"]["file"])
        cls.base = base

    def setUp(self):
        self.spy = StrictController()
        self.logger = logging.getLogger("bettercoc.test.dryrun")
        self.logger.addHandler(logging.NullHandler())
        self.logger.propagate = False
        self.temp_dir = make_temp_dir("dry-run")

    def _context(self, image, dry_run=True, reload_timeout=0.0):
        config = Config.from_dict(
            {
                "runtime": {
                    "dry_run": dry_run,
                    "reload_timeout": reload_timeout,
                    "screenshot_dir": str(self.temp_dir / "screenshots"),
                }
            }
        )
        return Context(
            config=config,
            vision=self.vision,
            capture=StaticCapture(image),
            controller=self.spy,
            logger=self.logger,
            canonical=(1920, 1080),
            dry_run=dry_run,
            jitter=0,
            tap_delay=(0.0, 0.0),
            sleeper=lambda seconds: None,
        )

    def test_tap_swipe_back_do_not_reach_controller(self):
        ctx = self._context(self.home_image)
        ctx.tap(120, 340)
        ctx.swipe(100, 500, 100, 900)
        ctx.back()
        ctx.screen()
        ctx.tap_match(ctx.wait("home_attack", timeout=1))
        self.assertEqual(self.spy.calls, [])
        self.assertEqual(ctx.stats.get("taps"), 2)
        self.assertEqual(ctx.stats.get("swipes"), 1)
        self.assertEqual(ctx.stats.get("backs"), 1)

    def test_reload_skips_device_input_in_dry_run(self):
        ctx = self._context(self.dialog_image)
        with self.assertRaises(TaskError):
            reload_if_stopped(ctx)
        self.assertEqual(self.spy.calls, [])

    def test_restart_game_refused_in_dry_run(self):
        ctx = self._context(self.home_image)
        with self.assertRaises(TaskError):
            restart_game(ctx)
        self.assertEqual(self.spy.calls, [])

    def test_zoom_out_min_skips_device_input_in_dry_run(self):
        ctx = self._context(self.home_image)
        _zoom_out_min(ctx)
        self.assertEqual(self.spy.calls, [])

    def test_real_mode_does_reach_controller(self):
        ctx = self._context(self.home_image, dry_run=False)
        with self.assertRaises(AssertionError):
            ctx.tap(120, 340)
        self.assertEqual(self.spy.calls[0][0], "tap")


if __name__ == "__main__":
    unittest.main()
