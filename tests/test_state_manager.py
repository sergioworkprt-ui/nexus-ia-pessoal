"""
NEXUS Test Suite — State Manager
Tests for: RuntimeState, StateManager (checkpoint, restore, rollback,
persistence, context store).
"""

import json
import os
import time
import unittest

from conftest import NexusTestCase

from nexus_runtime.state_manager import RuntimeState, StateManager, Checkpoint


# ---------------------------------------------------------------------------
# RuntimeState
# ---------------------------------------------------------------------------

class TestRuntimeState(NexusTestCase):

    def test_default_state(self) -> None:
        state = RuntimeState()
        self.assertEqual(state.cycle_count, 0)
        self.assertEqual(state.runtime_mode, "simulation")
        self.assertIsNotNone(state.state_id)

    def test_to_dict_has_required_keys(self) -> None:
        state = RuntimeState()
        d = state.to_dict()
        for key in ("state_id", "runtime_mode", "cycle_count",
                    "modules", "pipeline_last_run", "pipeline_runs"):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_from_dict_roundtrip(self) -> None:
        state = RuntimeState(runtime_mode="live", cycle_count=42)
        state.modules["core"] = True
        d = state.to_dict()
        restored = RuntimeState.from_dict(d)
        self.assertEqual(restored.cycle_count, 42)
        self.assertEqual(restored.runtime_mode, "live")
        self.assertTrue(restored.modules["core"])

    def test_pipeline_runs_default_zero(self) -> None:
        state = RuntimeState()
        for k in ("intelligence", "financial", "evolution", "consensus", "reporting"):
            self.assertEqual(state.pipeline_runs.get(k, 0), 0)


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------

class TestStateManager(NexusTestCase):

    def _make_manager(self, name: str = "checkpoint.json") -> StateManager:
        cp_dir = self.tmp_subdir("runtime")
        return StateManager(
            checkpoint_path=os.path.join(cp_dir, name),
            max_checkpoints=3,
        )

    def test_restore_or_init_fresh(self) -> None:
        sm = self._make_manager()
        restored = sm.restore_or_init("simulation")
        self.assertFalse(restored, "Should return False on fresh init")
        self.assertEqual(sm.state.runtime_mode, "simulation")

    def test_save_checkpoint_creates_file(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        cp = sm.save_checkpoint()
        self.assertTrue(os.path.isfile(cp.path))
        self.assertGreater(cp.size_bytes, 0)

    def test_restore_from_checkpoint(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        sm.state.cycle_count = 77
        sm.save_checkpoint()

        sm2 = StateManager(
            checkpoint_path=sm._base_path, max_checkpoints=3
        )
        restored = sm2.restore_or_init()
        self.assertTrue(restored, "Should restore from existing checkpoint")
        self.assertEqual(sm2.state.cycle_count, 77)

    def test_rollback_to_previous_checkpoint(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        sm.state.cycle_count = 10
        sm.save_checkpoint()        # checkpoint 0: cycle=10
        sm.state.cycle_count = 20
        sm.save_checkpoint()        # checkpoint 1: cycle=20
        ok = sm.rollback()
        self.assertTrue(ok)
        self.assertEqual(sm.state.cycle_count, 10)

    def test_rollback_fails_with_single_checkpoint(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        sm.save_checkpoint()
        ok = sm.rollback()
        self.assertFalse(ok, "Cannot rollback with only one checkpoint")

    def test_rolling_window_max_checkpoints(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        for i in range(5):
            sm.state.cycle_count = i
            sm.save_checkpoint()
        checkpoints = sm.list_checkpoints()
        self.assertLessEqual(len(checkpoints), 3)

    def test_mark_module_ready(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        sm.mark_module_ready("core")
        self.assertTrue(sm.state.modules["core"])

    def test_record_pipeline_run_increments_counter(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        sm.record_pipeline_run("financial", ok=True)
        sm.record_pipeline_run("financial", ok=True)
        self.assertEqual(sm.state.pipeline_runs["financial"], 2)

    def test_record_pipeline_run_tracks_errors(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        sm.record_pipeline_run("consensus", ok=False)
        self.assertEqual(sm.state.pipeline_errors["consensus"], 1)

    def test_record_pipeline_run_updates_last_run(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        self.assertIsNone(sm.state.pipeline_last_run["intelligence"])
        sm.record_pipeline_run("intelligence", ok=True)
        self.assertIsNotNone(sm.state.pipeline_last_run["intelligence"])

    def test_increment_cycle(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        self.assertEqual(sm.increment_cycle(), 1)
        self.assertEqual(sm.increment_cycle(), 2)

    def test_set_and_get_context(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        sm.set_context("last_sentiment_score", 0.42)
        val = sm.get_context("last_sentiment_score")
        self.assertAlmostEqual(val, 0.42)

    def test_get_context_missing_returns_default(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        val = sm.get_context("nonexistent", default="fallback")
        self.assertEqual(val, "fallback")

    def test_context_persists_in_checkpoint(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        sm.set_context("test_key", {"value": 99})
        sm.save_checkpoint()

        sm2 = StateManager(checkpoint_path=sm._base_path, max_checkpoints=3)
        sm2.restore_or_init()
        self.assertEqual(sm2.get_context("test_key"), {"value": 99})

    def test_current_state_dict(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        d = sm.current_state_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("cycle_count", d)

    def test_uptime_increases_over_time(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        t1 = sm.current_state_dict()["uptime_seconds"]
        time.sleep(0.05)
        t2 = sm.current_state_dict()["uptime_seconds"]
        self.assertGreater(t2, t1)

    def test_list_checkpoints_returns_list(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        sm.save_checkpoint()
        cps = sm.list_checkpoints()
        self.assertIsInstance(cps, list)
        self.assertGreater(len(cps), 0)

    def test_checkpoint_index_file_created(self) -> None:
        sm = self._make_manager()
        sm.restore_or_init()
        sm.save_checkpoint()
        index_path = os.path.join(sm._dir, StateManager.INDEX_FILENAME)
        self.assertTrue(os.path.isfile(index_path))
        with open(index_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)


if __name__ == "__main__":
    unittest.main()
