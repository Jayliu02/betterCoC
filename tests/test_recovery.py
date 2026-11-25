import unittest

import numpy as np

from bettercoc.errors import MissingAssetError, TaskError
from bettercoc.geometry import Rect
from bettercoc.image import normalize_frame
from bettercoc.recovery import _is_loading, ensure_home, reload_if_stopped, restart_game
from bettercoc.result import Match


class FakeLogger:
    def __init__(self):
        self.records = []

    def warning(self, message, *args):
        self.records.append(("warning", message % args if args else message))

    def info(self, message, *args):
        self.records.append(("info", message % args if args else message))

    def exception(self, message, *args):
        self.records.append(("error", message % args if args else message))

    def error(self, message, *args):
        self.records.append(("error", message % args if args else message))

    def debug(self, *args, **kwargs):
        pass


class FakeStats:
    def __init__(self):
        self.counters = {}

    def incr(self, key, amount=1):
        self.counters[key] = self.counters.get(key, 0) + amount


class FakeAssets:
    def __init__(self, names):
        self.names = set(names)

    def has(self, name):
        return name in self.names


class FakeVision:
    def __init__(self, names):
        self.assets = FakeAssets(names)


class FakeConfig:
    def __init__(self, data):
        self.data = data

    def get(self, dotted, default=None):
        current = self.data
        for part in dotted.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current


class FakeContext:
    def __init__(self, stop_matches=1, home_after=True, assets=None, timeout=5.0):
        names = {"game_stop", "home_attack"} if assets is None else set(assets)
        self.vision = FakeVision(names)
        self.config = FakeConfig({"runtime": {"reload_timeout": timeout}})
        self.stats = FakeStats()
        self.logger = FakeLogger()
        self.now = 0.0
        self.stop_matches = stop_matches
        self.home_after = home_after
        self.taps = []
        self.saved = []
        self.screens = 0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)

    def should_stop(self):
        return False

    def screen(self):
        self.screens += 1
        return object()

    def find_optional(self, name, screen=None, roi=None):
        if name == "game_stop":
            if self.stop_matches > 0:
                self.stop_matches -= 1
                return Match(rect=Rect(486, 604, 184, 56), score=1.0, name=name)
            return None
        if name == "home_attack" and self.home_after:
            return Match(rect=Rect(0, 800, 240, 260), score=0.99, name=name)
        return None

    def tap_match(self, match, offset=(0, 0)):
        self.taps.append(match)

    def save_screenshot(self, label, screen=None):
        self.saved.append(label)


class ReloadIfStoppedTest(unittest.TestCase):
    def test_clicks_reload_and_waits_for_home(self):
        ctx = FakeContext(stop_matches=1)
        self.assertTrue(reload_if_stopped(ctx))
        self.assertEqual([match.name for match in ctx.taps], ["game_stop"])
        self.assertEqual(ctx.stats.counters.get("game_reloads"), 1)
        self.assertEqual(ctx.saved, ["game-stopped"])
        self.assertIn("重新载入游戏", " ".join(message for _, message in ctx.logger.records))

    def test_no_dialog_does_nothing(self):
        ctx = FakeContext(stop_matches=0)
        self.assertFalse(reload_if_stopped(ctx))
        self.assertEqual(ctx.taps, [])
        self.assertNotIn("game_reloads", ctx.stats.counters)

    def test_missing_asset_is_ignored(self):
        ctx = FakeContext(stop_matches=1, assets={"home_attack"})
        self.assertFalse(reload_if_stopped(ctx))
        self.assertEqual(ctx.taps, [])

    def test_timeout_raises(self):
        ctx = FakeContext(stop_matches=1, home_after=False)
        with self.assertRaises(TaskError):
            reload_if_stopped(ctx)
        self.assertGreaterEqual(ctx.now, 5.0)

    def test_still_stopped_clicks_again(self):
        ctx = FakeContext(stop_matches=2, timeout=10.0)
        self.assertTrue(reload_if_stopped(ctx))
        self.assertEqual([match.name for match in ctx.taps], ["game_stop", "game_stop"])


class HomeContext:
    def __init__(self, home_asset=True):
        self.vision = FakeVision(
            {"home_attack", "exit_cancel"} if home_asset else set()
        )
        self.logger = FakeLogger()
        self.taps = []
        self.backs = 0
        self.saved = []
        self.screens = 0
        self.state = "dialog"

    def should_stop(self):
        return False

    def screen(self):
        self.screens += 1
        return object()

    def find_optional(self, name, screen=None, roi=None):
        if name == "exit_cancel" and self.state == "dialog":
            return Match(rect=Rect(746, 770, 1, 1), score=1.0, name=name)
        return None

    def find(self, name, screen=None, roi=None):
        if name == "home_attack" and self.state == "home":
            return Match(rect=Rect(110, 935, 1, 1), score=1.0, name=name)
        return None

    def tap_match(self, match, offset=(0, 0)):
        self.taps.append(match.name)
        if match.name == "exit_cancel":
            self.state = "home"

    def back(self):
        self.backs += 1

    def sleep(self, seconds):
        pass

    def save_screenshot(self, label, screen=None):
        self.saved.append(label)


class EnsureHomeTest(unittest.TestCase):
    def test_cancels_exit_dialog_then_returns_home(self):
        ctx = HomeContext()
        ensure_home(ctx)
        self.assertEqual(ctx.taps, ["exit_cancel"])
        self.assertEqual(ctx.backs, 0)

    def test_home_visible_without_dialog(self):
        ctx = HomeContext()
        ctx.state = "home"
        ensure_home(ctx)
        self.assertEqual(ctx.taps, [])

    def test_missing_home_asset_raises(self):
        ctx = HomeContext(home_asset=False)
        with self.assertRaises(MissingAssetError):
            ensure_home(ctx)

    def test_failure_saves_screenshot(self):
        class StuckContext(HomeContext):
            def find_optional(self, name, screen=None, roi=None):
                return None

            def find(self, name, screen=None, roi=None):
                return None

        ctx = StuckContext()
        with self.assertRaises(TaskError):
            ensure_home(ctx)
        self.assertEqual(ctx.saved, ["ensure-home-failed"])
        self.assertEqual(ctx.backs, 8)


class BattleContext(HomeContext):
    def __init__(self):
        super().__init__()
        self.state = "battle"

    def find_optional(self, name, screen=None, roi=None):
        if name == "scout_cancel" and self.state in ("battle", "confirm"):
            return Match(rect=Rect(140, 810, 1, 1), score=1.0, name=name)
        if name == "battle_confirm" and self.state == "confirm":
            return Match(rect=Rect(1158, 776, 1, 1), score=1.0, name=name)
        if name == "battle_return_home" and self.state == "result":
            return Match(rect=Rect(961, 932, 1, 1), score=1.0, name=name)
        return None

    def tap_match(self, match, offset=(0, 0)):
        self.taps.append(match.name)
        if match.name == "scout_cancel":
            self.state = "confirm"
        elif match.name == "battle_confirm":
            self.state = "result"
        elif match.name == "battle_return_home":
            self.state = "home"


class EnsureHomeBattleTest(unittest.TestCase):
    def test_ends_scouting_and_confirms(self):
        ctx = BattleContext()
        ensure_home(ctx)
        self.assertEqual(
            ctx.taps, ["scout_cancel", "battle_confirm", "battle_return_home"]
        )

    def test_loading_screen_is_detected(self):
        white = normalize_frame(
            np.full((1080, 1920, 3), 250, dtype=np.uint8), (1920, 1080)
        )
        self.assertTrue(_is_loading(white))
        dark = normalize_frame(
            np.full((1080, 1920, 3), 100, dtype=np.uint8), (1920, 1080)
        )
        self.assertFalse(_is_loading(dark))


class FakeController:
    def __init__(self, ctx=None):
        self.ctx = ctx
        self.stopped = []
        self.started = []

    def force_stop(self, package):
        self.stopped.append(package)
        if self.ctx is not None:
            self.ctx.phase = "splash"

    def start_app(self, package):
        self.started.append(package)
        if self.ctx is not None:
            self.ctx.phase = "ad"


class RestartContext(FakeContext):
    def __init__(self, timeout=10.0):
        super().__init__(stop_matches=0, timeout=timeout)
        self.config.data["runtime"]["game_package"] = "com.test.coc"
        self.config.data["runtime"]["restart_timeout"] = timeout
        self.controller = FakeController()
        self.dry_run = False
        self.phase = "splash"

    def find_optional(self, name, screen=None, roi=None):
        if name == "home_popup_close" and self.phase == "ad":
            self.phase = "home"
            return Match(rect=Rect(1600, 80, 80, 78), score=1.0, name=name)
        if name == "home_attack" and self.phase == "home":
            return Match(rect=Rect(0, 800, 240, 260), score=0.99, name=name)
        return None


class RestartGameTest(unittest.TestCase):
    def test_closes_startup_ad_and_returns_home(self):
        ctx = RestartContext()
        ctx.controller = FakeController(ctx)
        restart_game(ctx)
        self.assertEqual(ctx.controller.stopped, ["com.test.coc"])
        self.assertEqual(ctx.controller.started, ["com.test.coc"])
        self.assertEqual([match.name for match in ctx.taps], ["home_popup_close"])
        self.assertEqual(ctx.stats.counters.get("game_restarts"), 1)
        self.assertEqual(ctx.saved, ["game-restart"])

    def test_dry_run_refuses(self):
        ctx = RestartContext()
        ctx.dry_run = True
        with self.assertRaises(TaskError):
            restart_game(ctx)
        self.assertEqual(ctx.controller.stopped, [])

    def test_missing_controller_capability(self):
        ctx = RestartContext()
        ctx.controller = object()
        with self.assertRaises(TaskError):
            restart_game(ctx)

    def test_timeout_raises(self):
        ctx = RestartContext(timeout=10.0)
        ctx.controller = FakeController()
        with self.assertRaises(TaskError):
            restart_game(ctx)
        self.assertGreaterEqual(ctx.now, 10.0)
        self.assertEqual(ctx.controller.started, ["com.test.coc"])


if __name__ == "__main__":
    unittest.main()
