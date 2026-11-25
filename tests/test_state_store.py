import json
import unittest
from pathlib import Path
from unittest import mock

from bettercoc.state_store import (
    Observation,
    StateError,
    StateSource,
    StateStatus,
    StateStore,
)

from support import make_temp_dir


class FakeClock:
    def __init__(self, value: float = 1_000_000.0) -> None:
        self.now = value

    def __call__(self) -> float:
        return self.now


class StateStoreTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()

    def test_observed_value_is_valid(self):
        store = StateStore(clock=self.clock)
        observation = store.observe("gold", 1234, frame_id="frame-1")
        self.assertEqual(observation.status, StateStatus.VALID)
        self.assertEqual(observation.source, StateSource.OBSERVED)
        self.assertEqual(observation.frame_id, "frame-1")
        self.assertEqual(store.value("gold"), 1234)

    def test_missing_is_not_zero(self):
        store = StateStore(clock=self.clock)
        store.observe("gold", None, frame_id="frame-1")
        self.assertIsNone(store.value("gold"))
        self.assertIsNone(store.value("elixir"))
        observation = store.get("gold")
        self.assertEqual(observation.status, StateStatus.UNKNOWN)
        self.assertEqual(observation.value, None)
        self.assertIn("未观测", observation.reason)

    def test_zero_is_a_real_value(self):
        store = StateStore(clock=self.clock)
        store.observe("dark", 0)
        self.assertEqual(store.value("dark"), 0)
        self.assertEqual(store.get("dark").status, StateStatus.VALID)

    def test_stale_observation(self):
        store = StateStore(clock=self.clock, stale_after=60)
        store.observe("gold", 100)
        self.clock.now += 61
        observation = store.get("gold")
        self.assertEqual(observation.status, StateStatus.STALE)
        self.assertEqual(observation.value, 100)
        self.assertIn("过期", observation.reason)

    def test_configured_fallback_does_not_override_observation(self):
        store = StateStore(clock=self.clock)
        fallback = store.fallback("gold_max", 10_000_000)
        self.assertEqual(fallback.source, StateSource.CONFIGURED)
        self.assertEqual(fallback.value, 10_000_000)
        store.observe("gold_max", 12_000_000)
        result = store.fallback("gold_max", 10_000_000)
        self.assertEqual(result.value, 12_000_000)
        self.assertEqual(result.source, StateSource.OBSERVED)

    def test_estimated_source_is_distinguishable(self):
        store = StateStore(clock=self.clock)
        store.observe("gold", 5_000_000)
        estimate = store.estimate("gold", 4_400_000, reason="扣减升级费用")
        self.assertEqual(estimate.source, StateSource.ESTIMATED)
        self.assertEqual(estimate.status, StateStatus.VALID)

    def test_capacity_check_does_not_flag_error(self):
        store = StateStore(clock=self.clock)
        store.observe("elixir", 11_639_746)
        store.observe("elixir_max", 10_000_000)
        result = store.capacity_check("elixir", "elixir_max")
        self.assertEqual(result["status"], "over_capacity")
        self.assertIn("不能直接判为错误", result["reason"])
        missing = store.capacity_check("gold", "gold_max")
        self.assertEqual(missing["status"], "unknown")
        store.observe("gold", 100)
        no_limit = store.capacity_check("gold", "gold_max")
        self.assertEqual(no_limit["status"], "unknown")
        self.assertIn("上限缺失", no_limit["reason"])

    def test_save_and_load_new_format(self):
        temp = make_temp_dir("state")
        path = temp / "state.json"
        store = StateStore(path, clock=self.clock)
        store.observe("gold", 42, frame_id="frame-9")
        store.configured("gold_max", 10_000_000)
        store.save()
        self.assertTrue(path.exists())
        self.assertFalse(path.with_name(path.name + ".tmp").exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["states"]["gold"]["source"], "observed")
        loaded = StateStore(path, clock=self.clock).load()
        self.assertFalse(loaded.loaded_legacy)
        self.assertEqual(loaded.get("gold").value, 42)
        self.assertEqual(loaded.get("gold").frame_id, "frame-9")
        self.assertEqual(loaded.get("gold_max").source, StateSource.CONFIGURED)
        self.assertIsNone(loaded.load_error)

    def test_legacy_format_is_readable(self):
        temp = make_temp_dir("state-legacy")
        path = temp / "resource-state.json"
        path.write_text(
            json.dumps(
                {
                    "gold": 234_789,
                    "elixir": 9_400_000,
                    "gold_max": 10_000_000,
                    "updated_at": "2026-11-24 12:00:00",
                }
            ),
            encoding="utf-8",
        )
        store = StateStore(path, clock=self.clock).load()
        self.assertTrue(store.loaded_legacy)
        observation = store.get("gold")
        self.assertEqual(observation.value, 234_789)
        self.assertEqual(observation.source, StateSource.CACHED)
        self.assertIsNone(observation.observed_at)
        self.assertEqual(store.get("gold_max").value, 10_000_000)
        self.assertIsNone(store.get("dark"))

    def test_corrupt_file_sets_load_error(self):
        temp = make_temp_dir("state-corrupt")
        path = temp / "state.json"
        path.write_text("{not json", encoding="utf-8")
        store = StateStore(path, clock=self.clock).load()
        self.assertIsNotNone(store.load_error)
        self.assertEqual(store.keys(), [])

    def test_write_failure_keeps_old_file(self):
        temp = make_temp_dir("state-fail")
        path = temp / "state.json"
        path.write_text('{"schema_version": 1, "states": {}}', encoding="utf-8")
        original = path.read_text(encoding="utf-8")
        store = StateStore(path, clock=self.clock)
        store.observe("gold", 1)
        with mock.patch(
            "bettercoc.state_store.write_json_atomic", side_effect=OSError("disk full")
        ):
            with self.assertRaises(StateError):
                store.save()
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_observation_roundtrip(self):
        observation = Observation(
            key="gold",
            value=5,
            source=StateSource.OBSERVED,
            status=StateStatus.VALID,
            observed_at=123.0,
            frame_id="f",
            reason="",
        )
        restored = Observation.from_dict("gold", observation.to_dict())
        self.assertEqual(restored, observation)
        unknown = Observation.from_dict("gold", {"value": None, "source": "observed"})
        self.assertEqual(unknown.status, StateStatus.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
