import json
import unittest
from pathlib import Path

from bettercoc.baseline import (
    build_vision_from_manifest,
    load_fixture_manifest,
    measure,
    percentile,
    verify_fixtures,
)

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "baseline"
REQUIRED_TAGS = {
    "home",
    "attack_menu",
    "scouting",
    "battle",
    "wall",
    "popup",
    "dialog",
    "disconnect",
    "scaled",
    "cropped",
    "blurred",
    "dimmed",
    "noise",
}


class BaselineFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_fixture_manifest(FIXTURES)
        cls.vision = build_vision_from_manifest(cls.manifest)

    def test_manifest_integrity(self):
        self.assertEqual(verify_fixtures(self.manifest), [])
        self.assertGreaterEqual(len(self.manifest["frames"]), 30)
        base = Path(self.manifest["_dir"])
        for frame in self.manifest["frames"]:
            self.assertTrue(
                (base / frame["file"]).exists(), f"缺少基准帧 {frame['id']}"
            )
            self.assertTrue(frame.get("labels"), f"{frame['id']} 没有标注")
            self.assertTrue(frame.get("source", {}).get("path"), frame["id"])

    def test_category_coverage(self):
        tags = {tag for frame in self.manifest["frames"] for tag in frame.get("tags", [])}
        missing = REQUIRED_TAGS - tags
        self.assertEqual(missing, set())

    def test_fixture_labels(self):
        base = Path(self.manifest["_dir"])
        canonical = tuple(self.manifest.get("canonical_size", [1920, 1080]))
        failures = []
        defects = []
        resolved = []
        for frame in self.manifest["frames"]:
            image_path = base / frame["file"]
            from bettercoc.image import load_image, normalize_frame

            screen = normalize_frame(load_image(image_path), canonical)
            for name, expected in sorted(frame["labels"].items()):
                with self.subTest(frame=frame["id"], asset=name):
                    match = self.vision.find(screen, name)
                    actual = "hit" if match is not None else "miss"
                    if expected == "hit":
                        if match is None:
                            failures.append(f"{frame['id']}:{name} 期望命中但未命中")
                    elif expected == "miss":
                        if match is not None:
                            failures.append(
                                f"{frame['id']}:{name} 期望未命中但命中 "
                                f"score={match.score:.3f} rect={match.rect}"
                            )
                    elif expected == "known_defect":
                        if match is None:
                            resolved.append(f"{frame['id']}:{name} 已不再命中")
                        else:
                            defects.append(f"{frame['id']}:{name} score={match.score:.3f}")
                    else:
                        failures.append(f"{frame['id']}:{name} 标签无效 {expected}")
        self.assertEqual(failures, [])
        self.assertLessEqual(len(defects), 1)
        if resolved:
            self.assertEqual(resolved, [], "已知缺陷已修复，更新 manifest 标注")

    def test_quality_gate(self):
        base = Path(self.manifest["_dir"])
        canonical = tuple(self.manifest.get("canonical_size", [1920, 1080]))
        from bettercoc.image import load_image, normalize_frame

        total = 0
        hits = 0
        for frame in self.manifest["frames"]:
            screen = normalize_frame(load_image(base / frame["file"]), canonical)
            for name, expected in frame["labels"].items():
                if expected != "hit":
                    continue
                total += 1
                if self.vision.find(screen, name) is not None:
                    hits += 1
        self.assertGreater(total, 0)
        self.assertEqual(hits, total)


class MeasureUtilityTest(unittest.TestCase):
    def test_percentile(self):
        values = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(percentile([], 0.5), 0.0)
        self.assertEqual(percentile([5.0], 0.95), 5.0)
        self.assertAlmostEqual(percentile(values, 0.5), 2.5)
        self.assertAlmostEqual(percentile(values, 0.95), 3.85)

    def test_measure_collects_samples_and_errors(self):
        state = {"calls": 0, "fail": False}

        def work():
            state["calls"] += 1
            if state["fail"]:
                raise RuntimeError("boom")

        stats = measure("work", work, iterations=5, warmup=0)
        self.assertEqual(stats["samples"], 5)
        self.assertEqual(stats["errors"], 0)
        self.assertEqual(stats["iterations"], 5)
        self.assertGreaterEqual(stats["p50_ms"], 0.0)
        self.assertGreaterEqual(stats["max_ms"], stats["min_ms"])

        state["fail"] = True
        failing = measure("work", work, iterations=3, warmup=0)
        self.assertEqual(failing["samples"], 0)
        self.assertEqual(failing["errors"], 3)
        self.assertIn("boom", failing["last_error"])

    def test_measure_zero_iterations_still_runs(self):
        stats = measure("noop", lambda: None, iterations=0, warmup=0)
        self.assertEqual(stats["iterations"], 1)
        self.assertEqual(stats["samples"], 1)


if __name__ == "__main__":
    unittest.main()
