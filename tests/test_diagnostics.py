import json
import unittest
from pathlib import Path

from bettercoc.baseline import build_vision_from_manifest, load_fixture_manifest
from bettercoc.errors import (
    CaptureError,
    DeviceError,
    MissingAssetError,
    RecognitionTimeout,
    StopRequested,
)
from bettercoc.events import (
    ErrorCode,
    EventLog,
    EventType,
    classify_error,
)
from bettercoc.result import Match
from bettercoc.geometry import Rect
from bettercoc.recorder import Recorder, RecorderLimits, record_fixture_session
from bettercoc.replay import ReplaySession
from bettercoc.frame import Frame

from support import make_temp_dir

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "baseline"


class EventLogTest(unittest.TestCase):
    def test_recognition_event_fields(self):
        temp = make_temp_dir("events")
        path = temp / "events.jsonl"
        log = EventLog("run-1", path=path, max_events=10)
        match = Match(
            rect=Rect(10, 20, 30, 40),
            score=0.91,
            name="home_attack",
            frame_id="frame-1",
            threshold=0.86,
        )
        event = log.recognition(
            "home_attack", match, frame_id="frame-1", duration_ms=4.5
        )
        miss = log.recognition("game_stop", None, frame_id="frame-1", duration_ms=1.0)
        log.close()
        data = event.to_dict()
        self.assertEqual(data["event_type"], "recognition")
        self.assertEqual(data["run_id"], "run-1")
        self.assertEqual(data["frame_id"], "frame-1")
        self.assertEqual(data["status"], "matched")
        self.assertAlmostEqual(data["score"], 0.91)
        self.assertEqual(data["bbox"], [10, 20, 30, 40])
        self.assertEqual(data["threshold"], 0.86)
        self.assertTrue(data["recognition_id"].startswith("run-1-r"))
        self.assertEqual(miss.error_code, ErrorCode.RECOGNITION_MISS.value)
        lines = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["recognition_id"], data["recognition_id"])

    def test_coordinate_only_status_recorded(self):
        log = EventLog("run-2", max_events=5)
        match = Match(rect=Rect(1, 1, 1, 1), name="build_button", status="coordinate_only")
        event = log.recognition("build_button", match, frame_id="f", duration_ms=0.1)
        self.assertEqual(event.status, "coordinate_only")

    def test_bounded_log_counts_dropped(self):
        log = EventLog("run-3", max_events=2)
        for index in range(5):
            log.emit(EventType.CAPTURE, message=f"frame {index}")
        self.assertEqual(len(log), 2)
        self.assertEqual(log.dropped, 3)
        self.assertEqual(len(log.recent(10)), 2)

    def test_error_counts_and_classification(self):
        log = EventLog("run-4", max_events=10)
        log.error(MissingAssetError("missing"))
        log.error(RecognitionTimeout("timeout"))
        log.error(StopRequested("stop"))
        log.error(CaptureError("capture"))
        log.error(ValueError("boom"))
        counts = log.error_counts()
        self.assertEqual(counts.get("asset_missing"), 1)
        self.assertEqual(counts.get("timeout"), 1)
        self.assertEqual(counts.get("cancelled"), 1)
        self.assertEqual(counts.get("capture_failed"), 1)
        self.assertEqual(counts.get("internal_error"), 1)
        self.assertEqual(classify_error(OSError("disk")), ErrorCode.STORAGE_FAILED)
        self.assertEqual(classify_error(DeviceError("adb")), ErrorCode.DEVICE_UNAVAILABLE)
        self.assertEqual(classify_error(ValueError("x")), ErrorCode.INTERNAL_ERROR)


class RecorderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_fixture_manifest(FIXTURES)
        cls.vision = build_vision_from_manifest(cls.manifest)
        size = cls.manifest["canonical_size"]
        cls.canonical = (int(size[0]), int(size[1]))

    def _frame(self, frame_id="unit-1", image=None):
        import numpy as np

        from bettercoc.geometry import Viewport

        pixels = image if image is not None else np.zeros((1080, 1920, 3), dtype=np.uint8)
        return Frame(
            frame_id=frame_id,
            source_id="unit",
            image=pixels,
            viewport=Viewport(1920, 1080, 1920, 1080),
            raw_size=(1920, 1080),
            captured_at=1.0,
            captured_wall=2.0,
            sequence=1,
        )

    def test_record_fixture_session_files(self):
        temp = make_temp_dir("recorder")
        recorder = record_fixture_session(
            self.manifest,
            self.vision,
            temp,
            frame_limit=1,
            names=["home_attack", "game_stop"],
        )
        session = recorder.session_dir
        self.assertTrue((session / "manifest.json").exists())
        self.assertTrue((session / "events.jsonl").exists())
        self.assertTrue((session / "report.json").exists())
        frames = list((session / "frames").glob("*.png"))
        self.assertEqual(len(frames), 1)
        manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertTrue(manifest["assets_fingerprint"]["templates_sha256"])
        self.assertEqual(manifest["frames"][0]["frame_id"], "home-a")
        self.assertEqual(manifest["frames"][0]["canonical_size"], [1920, 1080])
        report = json.loads((session / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["frames"], 1)
        self.assertEqual(report["events_recorded"], 3)
        events = [
            json.loads(line)
            for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        recognitions = [item for item in events if item["event_type"] == "recognition"]
        self.assertEqual(len(recognitions), 2)
        self.assertTrue(all(item["frame_id"] == "home-a" for item in recognitions))

    def test_recorder_frame_limit_marks_truncated(self):
        temp = make_temp_dir("recorder-limit")
        recorder = Recorder(
            temp,
            run_id="limit-run",
            canonical=self.canonical,
            source_id="unit",
            limits=RecorderLimits(max_frames=1),
        )
        recorder.start()
        first = self._frame("unit-1")
        second = self._frame("unit-2")
        self.assertIsNotNone(recorder.record_frame(first))
        self.assertIsNone(recorder.record_frame(second))
        self.assertTrue(recorder.counters.truncated)
        self.assertEqual(recorder.counters.frames_skipped, 1)
        recorder.finish()
        report = json.loads(
            (recorder.session_dir / "report.json").read_text(encoding="utf-8")
        )
        self.assertTrue(report["truncated"])
        self.assertEqual(report["frames"], 1)
        self.assertEqual(report["frames_skipped"], 1)


class ReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_fixture_manifest(FIXTURES)
        cls.vision = build_vision_from_manifest(cls.manifest)
        temp = make_temp_dir("replay")
        cls.recorder = record_fixture_session(
            cls.manifest,
            cls.vision,
            temp,
            frame_limit=2,
            names=["home_attack", "game_stop", "attack_find_match"],
        )
        cls.session = ReplaySession.load(cls.recorder.session_dir)

    def test_replay_reproduces_recorded_results(self):
        data = self.session.run(self.vision)
        self.assertEqual(data["summary"]["frames"], 2)
        self.assertEqual(data["summary"]["checks"], 74)
        self.assertEqual(data["summary"]["comparisons"], 6)
        self.assertEqual(data["mismatches"], [])
        self.assertFalse(data["assets_changed"])

    def test_replay_is_deterministic(self):
        first = self.session.run(self.vision)
        second = self.session.run(self.vision)
        first_scores = [
            check["score"]
            for frame in first["frames"]
            for check in frame["checks"]
        ]
        second_scores = [
            check["score"]
            for frame in second["frames"]
            for check in frame["checks"]
        ]
        self.assertEqual(first_scores, second_scores)
        self.assertEqual(len(first_scores), 74)

    def test_replay_frames_are_fresh_and_typed(self):
        frames = self.session.frames()
        self.assertEqual(len(frames), 2)
        for item in frames:
            self.assertFalse(item.frame.is_stale())
            self.assertEqual(item.frame.canonical_size, (1920, 1080))
            self.assertEqual(item.frame.viewport.device_width, 1920)
            self.assertTrue(item.file.exists())
            self.assertEqual(item.frame.image.flags.writeable, False)

    def test_asset_drift_is_reported(self):
        original = dict(self.session.recorded_assets)
        self.session.recorded_assets = dict(original)
        self.session.recorded_assets["templates_sha256"] = "deadbeef"
        drift = self.session.asset_drift(self.vision)
        self.assertTrue(drift["changed"])
        data = self.session.run(self.vision)
        self.assertTrue(data["assets_changed"])
        self.session.recorded_assets = original

    def test_replay_report_roundtrip(self):
        data = self.session.run(self.vision)
        target = self.session.root / "replay-report-test.json"
        self.session.write_report(target, data)
        loaded = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(loaded["run_id"], self.session.run_id)
        self.assertEqual(loaded["summary"]["mismatches"], 0)


if __name__ == "__main__":
    unittest.main()
