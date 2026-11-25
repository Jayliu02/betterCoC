import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
)

HAS_QT = importlib.util.find_spec("PySide6") is not None

from bettercoc.baseline import build_vision_from_manifest, load_fixture_manifest
from bettercoc.config import Config
from bettercoc.geometry import Rect
from bettercoc.studio.geometry import (
    canonical_point,
    canonical_rect,
    fit_image,
    image_to_widget,
    widget_to_image,
    zoomed_fit,
)
from bettercoc.studio.recognition import (
    evaluate_draft,
    export_draft,
    recognize_frame,
)
from bettercoc.studio.source import FixtureSource, SessionSource

FIXTURES = ROOT / "tests" / "fixtures" / "baseline"


class CanvasGeometryTest(unittest.TestCase):
    def test_native_size(self):
        fit = fit_image(1920, 1080, 1920, 1080)
        self.assertAlmostEqual(fit.scale, 1.0)
        self.assertAlmostEqual(fit.offset_x, 0.0)
        self.assertEqual(
            (round(fit.offset_y, 3), round(fit.drawn_height, 3)), (0.0, 1080.0)
        )

    def test_letterbox_padding(self):
        fit = fit_image(1920, 1080, 1600, 940)
        self.assertAlmostEqual(fit.scale, 1600 / 1920)
        self.assertAlmostEqual(fit.drawn_width, 1600)
        self.assertAlmostEqual(fit.offset_y, (940 - 1080 * (1600 / 1920)) / 2)
        self.assertGreater(fit.offset_y, 0)

    def test_non_uniform_window(self):
        fit = fit_image(1920, 1080, 1000, 900)
        self.assertAlmostEqual(fit.scale, 1000 / 1920)
        self.assertGreater(fit.offset_y, 0)
        self.assertLess(fit.offset_x, 1e-6)

    def test_roundtrip_within_one_canonical_pixel(self):
        canvas = (1237, 811)
        fit = fit_image(1920, 1080, *canvas)
        points = [
            (fit.offset_x, fit.offset_y),
            (12, 20 + fit.offset_y),
            (fit.offset_x + fit.drawn_width / 2, fit.offset_y + fit.drawn_height / 2),
            (
                fit.offset_x + fit.drawn_width - 0.5,
                fit.offset_y + fit.drawn_height - 0.5,
            ),
        ]
        for widget_point in points:
            canonical = canonical_point(fit, *widget_point, (1920, 1080))
            self.assertIsNotNone(canonical)
            widget = image_to_widget(fit, *canonical)
            back = canonical_point(fit, *widget, (1920, 1080))
            self.assertLessEqual(abs(back[0] - canonical[0]), 1)
            self.assertLessEqual(abs(back[1] - canonical[1]), 1)

    def test_points_outside_image(self):
        fit = fit_image(1920, 1080, 1600, 940)
        self.assertIsNone(widget_to_image(fit, 10, 10, clamp=False))
        self.assertIsNone(canonical_point(fit, 10, 10, (1920, 1080)))
        clamped = widget_to_image(fit, 0, 0, clamp=True)
        self.assertEqual(clamped, (0.0, 0.0))

    def test_canonical_rect_clamps(self):
        fit = fit_image(1920, 1080, 1920, 1080)
        rect = canonical_rect(fit, 1900, 1060, 5000, 5000, (1920, 1080))
        self.assertEqual(rect.x, 1900)
        self.assertEqual(rect.y, 1060)
        self.assertLessEqual(rect.right, 1920)
        self.assertLessEqual(rect.bottom, 1080)
        self.assertGreaterEqual(rect.width, 1)

    def test_zoomed_fit_keeps_center(self):
        fit = fit_image(1920, 1080, 1600, 900)
        zoomed = zoomed_fit(fit, 2.0)
        self.assertAlmostEqual(zoomed.scale, fit.scale * 2.0)
        self.assertAlmostEqual(
            zoomed.offset_x + zoomed.drawn_width / 2, 1600 / 2, places=3
        )


class SourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_fixture_manifest(FIXTURES)

    def test_fixture_source_frames(self):
        source = FixtureSource(FIXTURES)
        self.assertEqual(source.frame_count(), 32)
        item = source.frame(0)
        self.assertEqual(item.frame.frame_id, "home-a")
        self.assertEqual(item.frame.canonical_size, (1920, 1080))
        self.assertIn("home_attack", source.assets())
        self.assertEqual(source.expectations("home-a").get("home_attack"), "hit")

    def test_session_source_frames(self):
        from bettercoc.recorder import record_fixture_session
        from support import make_temp_dir

        vision = build_vision_from_manifest(self.manifest)
        temp = make_temp_dir("studio-session")
        recorder = record_fixture_session(
            self.manifest, vision, temp, frame_limit=1, names=["home_attack"]
        )
        source = SessionSource(recorder.session_dir)
        self.assertEqual(source.frame_count(), 1)
        item = source.frame(0)
        self.assertEqual(item.frame.frame_id, "home-a")
        self.assertTrue(item.events)
        self.assertTrue(any(event.get("event_type") == "recognition" for event in source.events()))


class RecognitionRowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_fixture_manifest(FIXTURES)
        cls.vision = build_vision_from_manifest(cls.manifest)
        cls.source = FixtureSource(FIXTURES)

    def test_rows_report_status_semantics(self):
        frame = self.source.frame(0).frame
        rows = recognize_frame(self.vision, frame, ["home_attack", "build_button", "game_stop", "battle_end"])
        by_name = {row.name: row for row in rows}
        self.assertEqual(by_name["home_attack"].status, "matched")
        self.assertEqual(by_name["build_button"].status, "coordinate_only")
        self.assertEqual(by_name["game_stop"].status, "miss")
        self.assertEqual(by_name["battle_end"].status, "unknown")
        self.assertIsNotNone(by_name["battle_end"].error)
        self.assertTrue(by_name["home_attack"].is_visual_evidence)
        self.assertFalse(by_name["build_button"].is_visual_evidence)


class TemplateTrialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_fixture_manifest(FIXTURES)
        cls.source = FixtureSource(FIXTURES)
        home = cls.source.frame(0).frame
        cls.crop = home.crop(Rect(1630, 815, 220, 230)).copy()

    def test_evaluate_draft_counts(self):
        result = evaluate_draft(
            self.manifest,
            self.crop,
            [0.8, 0.86, 0.9],
            grayscale=False,
            name="home_attack",
        )
        self.assertEqual(result["frames"], 32)
        totals = {
            item["threshold"]: item["counts"].get("true_positive", 0)
            for item in result["thresholds"]
        }
        self.assertTrue(any(value > 0 for value in totals.values()))
        self.assertIn("false_positive", str(result["thresholds"][0]))

    def test_export_draft_does_not_touch_assets(self):
        from support import make_temp_dir

        before = (ROOT / "assets" / "assets.yaml").read_bytes()
        temp = make_temp_dir("studio-draft")
        result = export_draft(
            temp / "draft", "my_button", self.crop, 0.87, grayscale=False
        )
        self.assertTrue(Path(result["template"]).exists())
        fragment = Path(result["fragment"]).read_text(encoding="utf-8")
        self.assertIn("assets:", fragment)
        self.assertIn("my_button", fragment)
        self.assertTrue(Path(result["readme"]).exists())
        self.assertEqual((ROOT / "assets" / "assets.yaml").read_bytes(), before)


class StudioConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_fixture_manifest(FIXTURES)
        cls.vision = build_vision_from_manifest(cls.manifest)
        cls.source = FixtureSource(FIXTURES)

    def test_gui_rows_match_direct_vision(self):
        for index in (0, 6):
            frame = self.source.frame(index).frame
            rows = recognize_frame(self.vision, frame)
            self.assertEqual(len(rows), len(self.vision.assets.names()))
            for row in rows:
                if row.status == "unknown":
                    self.assertIsNotNone(row.error, row.name)
                    continue
                match = self.vision.find(frame.to_screen(), row.name)
                expected_status = "miss" if match is None else match.status.value
                self.assertEqual(row.status, expected_status, row.name)
                if match is not None:
                    self.assertAlmostEqual(row.score, match.score, places=6)
                    self.assertGreaterEqual(row.duration_ms, 0.0)

    def test_roi_adjustment_limits_matching(self):
        from dataclasses import replace as dataclass_replace

        manifest_ids = [str(entry["id"]) for entry in self.manifest["frames"]]
        frame = self.source.frame(manifest_ids.index("wall-bulk-a")).frame
        spec = self.vision.assets.recognition("wall_add_1")
        self.assertIsNotNone(self.vision.find(frame.to_screen(), spec))
        outside = dataclass_replace(spec, roi=Rect(0, 0, 300, 300))
        self.assertIsNone(self.vision.find(frame.to_screen(), outside))
        inside = dataclass_replace(spec, roi=Rect(600, 650, 500, 300))
        self.assertIsNotNone(self.vision.find(frame.to_screen(), inside))

    def test_studio_has_no_device_input_paths(self):
        studio_root = ROOT / "bettercoc" / "studio"
        forbidden = ("controller.", "input tap", "input swipe", "keyevent", "force-stop")
        for path in studio_root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(
                    token,
                    text,
                    f"{path.name} 不应包含设备输入: {token}",
                )


@unittest.skipUnless(HAS_QT, "PySide6 未安装")
class StudioWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])
        cls.temp = Path(tempfile.mkdtemp(prefix="studio-test-", dir=Path(ROOT) / "runtime"))

    def test_window_loads_fixtures_and_renders(self):
        from bettercoc.studio.main_window import MainWindow
        from bettercoc.studio.recognition import recognize_frame

        config = Config.load(ROOT / "config" / "config.yaml")
        window = MainWindow(
            config=config,
            source_path=FIXTURES,
            workspace=self.temp,
            fixtures=FIXTURES,
        )
        try:
            self.assertEqual(window.frame_count(), 32)
            self.assertEqual(window._index, 0)
            window.step_frame(1)
            self.assertEqual(window._index, 1)
            item = window.source.frame(window._index)
            rows = recognize_frame(window.vision, item.frame, ["home_attack", "build_button"])
            window.vision_panel._on_recognized(rows)
            self.assertEqual(window.vision_panel.table.rowCount(), 2)
            for row in range(5):
                window.nav.setCurrentRow(row)
                self.app.processEvents()
            window.nav.setCurrentRow(0)
            window.template_panel.canvas.set_selection(Rect(1630, 815, 220, 230))
            window.template_panel.canvas.selectionChanged.emit(Rect(1630, 815, 220, 230))
            self.assertIsNotNone(window.template_panel.canvas.selection)
            with mock.patch(
                "bettercoc.studio.template_editor.QMessageBox.information"
            ):
                window.template_panel.export()
            drafts = list((self.temp / "drafts").glob("*"))
            self.assertTrue(drafts)
            target = self.temp / "window.png"
            rendered = window.render_screenshot(target, 1200, 800)
            self.assertTrue(Path(rendered).exists())
            self.assertGreater(Path(rendered).stat().st_size, 10_000)
            self.assertEqual(window.runner.pending, 0)
        finally:
            window.close()
            self.app.processEvents()

    def test_worker_queue_is_bounded(self):
        from bettercoc.studio.worker import BackgroundRunner

        runner = BackgroundRunner(max_pending=1)
        rejected: list[str] = []
        runner.rejected.connect(lambda job_id, reason: rejected.append(job_id))
        runner.submit("slow", lambda: time.sleep(0.2) or 1)
        accepted = runner.submit("second", lambda: 2)
        self.assertFalse(accepted)
        self.assertEqual(rejected, ["second"])
        runner.shutdown()
        self.assertEqual(runner.pending, 0)


class StudioCliTest(unittest.TestCase):
    @unittest.skipUnless(HAS_QT, "PySide6 未安装")
    def test_screenshot_cli(self):
        target = ROOT / "runtime" / "test-tmp" / "studio-cli.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / ".deps") + os.pathsep + str(ROOT)
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "bettercoc",
                "--config",
                str(ROOT / "config" / "config.yaml"),
                "studio",
                "--screenshot",
                str(target),
                "--offscreen",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
