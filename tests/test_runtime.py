"""
NEXUS Test Suite — Runtime Module
Tests for: NexusRuntime (simulation mode), EventBus (delivery, handlers),
Scheduler (recurring, one-shot, cancellation), and pipeline execution.
All tests run in simulation mode — no live IO.
"""

import threading
import time
import unittest

from conftest import NexusTestCase

from nexus_runtime import (
    NexusRuntime, EventBus, EventType, Event,
    Scheduler, TaskResult, TaskStatus,
    RuntimeConfig, PipelineMode, RuntimeMode,
    PipelineRunResult, PipelineStatus,
)
from nexus_runtime.state_manager import StateManager


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------

class TestEventBus(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.bus = EventBus()
        self.bus.start()

    def tearDown(self) -> None:
        self.bus.stop(drain_timeout=1.0)
        super().tearDown()

    def _wait_for(self, condition, timeout: float = 2.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return True
            time.sleep(0.02)
        return False

    def test_publish_and_receive_sync(self) -> None:
        received = []
        self.bus.subscribe(lambda e: received.append(e),
                           event_type=EventType.INFO)
        self.bus.emit(EventType.INFO, source="test", data={"msg": "hello"})
        ok = self._wait_for(lambda: len(received) > 0)
        self.assertTrue(ok, "Event not received within timeout")
        self.assertEqual(received[0].event_type, EventType.INFO)

    def test_wildcard_handler_receives_all(self) -> None:
        received = []
        self.bus.subscribe(lambda e: received.append(e))  # no event_type → wildcard
        self.bus.emit(EventType.INFO,    source="s1")
        self.bus.emit(EventType.WARNING, source="s2")
        ok = self._wait_for(lambda: len(received) >= 2)
        self.assertTrue(ok, f"Expected ≥2 events, got {len(received)}")

    def test_async_handler_called(self) -> None:
        received = []
        self.bus.subscribe(lambda e: received.append(e),
                           event_type=EventType.PATTERN_DETECTED,
                           async_mode=True)
        self.bus.emit(EventType.PATTERN_DETECTED, source="wi",
                      data={"type": "breakout"})
        ok = self._wait_for(lambda: len(received) > 0)
        self.assertTrue(ok, "Async handler not called within timeout")

    def test_unsubscribe_stops_delivery(self) -> None:
        received = []
        hid = self.bus.subscribe(lambda e: received.append(e),
                                 event_type=EventType.INFO)
        self.bus.unsubscribe(hid)
        self.bus.emit(EventType.INFO, source="test")
        time.sleep(0.15)
        self.assertEqual(len(received), 0)

    def test_correlation_id_propagated(self) -> None:
        received = []
        self.bus.subscribe(lambda e: received.append(e),
                           event_type=EventType.PIPELINE_COMPLETED)
        self.bus.emit(EventType.PIPELINE_COMPLETED, source="p",
                      data={}, correlation_id="run-42")
        ok = self._wait_for(lambda: len(received) > 0)
        self.assertTrue(ok)
        self.assertEqual(received[0].correlation_id, "run-42")

    def test_event_history_grows(self) -> None:
        self.bus.emit(EventType.INFO, source="t1")
        self.bus.emit(EventType.INFO, source="t2")
        ok = self._wait_for(lambda: len(self.bus.history()) >= 2)
        self.assertTrue(ok)

    def test_stats_returns_dict(self) -> None:
        stats = self.bus.stats()
        self.assertDictHasKeys(stats,
            "published", "dispatched", "dropped", "handler_errors")

    def test_handler_error_does_not_crash_bus(self) -> None:
        def bad_handler(e):
            raise ValueError("intentional error")
        self.bus.subscribe(bad_handler, event_type=EventType.INFO)
        self.bus.emit(EventType.INFO, source="test")
        time.sleep(0.15)
        stats = self.bus.stats()
        self.assertGreaterEqual(stats["handler_errors"], 1)

    def test_list_handlers(self) -> None:
        self.bus.subscribe(lambda e: None, event_type=EventType.INFO,
                           description="test handler")
        handlers = self.bus.list_handlers()
        self.assertIsInstance(handlers, list)
        descriptions = [h["description"] for h in handlers]
        self.assertIn("test handler", descriptions)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class TestScheduler(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.scheduler = Scheduler(tick_interval=0.05, max_concurrent=4)
        self.scheduler.start()

    def tearDown(self) -> None:
        self.scheduler.stop(wait=1.0)
        super().tearDown()

    def _wait_for(self, condition, timeout: float = 3.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return True
            time.sleep(0.05)
        return False

    def test_schedule_once_executes(self) -> None:
        results = []
        self.scheduler.schedule_once("one_shot", lambda: results.append(1),
                                     delay_seconds=0.0)
        ok = self._wait_for(lambda: len(results) > 0)
        self.assertTrue(ok, "One-shot task did not execute")

    def test_recurring_task_executes_multiple_times(self) -> None:
        count = [0]
        self.scheduler.schedule("tick", lambda: count.__setitem__(0, count[0] + 1),
                                 interval_seconds=0.1, run_immediately=True)
        ok = self._wait_for(lambda: count[0] >= 3)
        self.assertTrue(ok, f"Recurring task ran only {count[0]} times")

    def test_cancel_stops_execution(self) -> None:
        count = [0]
        tid = self.scheduler.schedule("cancel_me",
                                      lambda: count.__setitem__(0, count[0] + 1),
                                      interval_seconds=0.05, run_immediately=True)
        time.sleep(0.15)
        self.scheduler.cancel(tid)
        count_at_cancel = count[0]
        time.sleep(0.2)
        # After cancel, count should not increase significantly
        self.assertLessEqual(count[0] - count_at_cancel, 1)

    def test_cancel_by_name(self) -> None:
        self.scheduler.schedule("named_task", lambda: None, interval_seconds=1.0)
        ok = self.scheduler.cancel("named_task")
        self.assertTrue(ok)

    def test_list_tasks_includes_registered(self) -> None:
        self.scheduler.schedule("list_me", lambda: None, interval_seconds=60.0)
        tasks = self.scheduler.list_tasks()
        names = [t["name"] for t in tasks]
        self.assertIn("list_me", names)

    def test_stats_returns_dict(self) -> None:
        stats = self.scheduler.stats()
        self.assertDictHasKeys(stats, "executed", "failed", "missed", "active_tasks")

    def test_task_error_does_not_crash_scheduler(self) -> None:
        def broken():
            raise RuntimeError("task failed intentionally")
        self.scheduler.schedule_once("broken_task", broken)
        time.sleep(0.2)
        stats = self.scheduler.stats()
        self.assertGreaterEqual(stats["failed"], 1)

    def test_on_task_done_callback(self) -> None:
        results: list = []
        sched = Scheduler(tick_interval=0.05, on_task_done=results.append)
        sched.start()
        try:
            sched.schedule_once("cb_test", lambda: None, delay_seconds=0.0)
            deadline = time.time() + 2.0
            while not results and time.time() < deadline:
                time.sleep(0.05)
            self.assertNonEmpty(results)
            self.assertIsInstance(results[0], TaskResult)
        finally:
            sched.stop(wait=1.0)

    def test_history_records_runs(self) -> None:
        self.scheduler.schedule_once("hist_task", lambda: None)
        self._wait_for(lambda: len(self.scheduler.history()) > 0)
        h = self.scheduler.history(limit=5)
        self.assertIsInstance(h, list)

    def test_reschedule_changes_interval(self) -> None:
        tid = self.scheduler.schedule("rescheduled", lambda: None, interval_seconds=60.0)
        ok = self.scheduler.reschedule(tid, interval_seconds=120.0)
        self.assertTrue(ok)
        task = self.scheduler.get_task(tid)
        self.assertIsNotNone(task)
        self.assertEqual(task["interval_seconds"], 120.0)


# ---------------------------------------------------------------------------
# NexusRuntime — simulation mode
# ---------------------------------------------------------------------------

class TestNexusRuntimeSimulation(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        cfg = RuntimeConfig.simulation()
        cfg.state.checkpoint_path = self.tmp_path("runtime", "checkpoint.json")
        cfg.audit_log_path        = self.tmp_path("audit.jsonl")
        self.runtime = NexusRuntime(config=cfg)

    def tearDown(self) -> None:
        if self.runtime._running:
            self.runtime.stop()
        super().tearDown()

    def test_start_returns_true(self) -> None:
        ok = self.runtime.start()
        self.assertTrue(ok)
        self.assertTrue(self.runtime._running)

    def test_stop_sets_running_false(self) -> None:
        self.runtime.start()
        self.runtime.stop()
        self.assertFalse(self.runtime._running)

    def test_double_start_safe(self) -> None:
        self.runtime.start()
        ok2 = self.runtime.start()
        self.assertTrue(ok2)

    def test_status_returns_dict(self) -> None:
        self.runtime.start()
        status = self.runtime.status()
        self.assertDictHasKeys(status,
            "version", "running", "mode", "pipelines", "scheduler")

    def test_status_mode_simulation(self) -> None:
        self.runtime.start()
        self.assertEqual(self.runtime.status()["mode"], "simulation")

    def test_pipelines_registered(self) -> None:
        self.runtime.start()
        pipes = self.runtime.status()["pipelines"]
        for name in ("intelligence", "financial", "evolution",
                     "consensus", "reporting"):
            self.assertIn(name, pipes)

    def test_run_pipeline_intelligence(self) -> None:
        self.runtime.start()
        result = self.runtime.run_pipeline("intelligence")
        self.assertIsNotNone(result)
        self.assertIn(result.status, (PipelineStatus.SUCCESS, PipelineStatus.PARTIAL))

    def test_run_pipeline_financial(self) -> None:
        self.runtime.start()
        result = self.runtime.run_pipeline("financial")
        self.assertIsNotNone(result)
        self.assertTrue(result.ok)

    def test_run_pipeline_consensus(self) -> None:
        self.runtime.start()
        result = self.runtime.run_pipeline("consensus")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, PipelineRunResult)

    def test_run_pipeline_reporting(self) -> None:
        self.runtime.start()
        result = self.runtime.run_pipeline("reporting")
        self.assertIsNotNone(result)

    def test_run_all_pipelines_returns_five_results(self) -> None:
        self.runtime.start()
        results = self.runtime.run_all_pipelines()
        self.assertEqual(len(results), 5)

    def test_all_pipelines_succeed(self) -> None:
        self.runtime.start()
        results = self.runtime.run_all_pipelines()
        failures = [r for r in results if not r.ok and
                    r.status != PipelineStatus.SKIPPED]
        self.assertEqual(failures, [],
                         f"Failing pipelines: {[r.pipeline for r in failures]}")

    def test_history_populated_after_pipelines(self) -> None:
        self.runtime.start()
        self.runtime.run_pipeline("financial")
        history = self.runtime.history(limit=5)
        self.assertNonEmpty(history)

    def test_pipeline_run_updates_state(self) -> None:
        self.runtime.start()
        self.runtime.run_pipeline("consensus")
        state = self.runtime.state.current_state_dict()
        self.assertGreater(state["cycle_count"], 0)

    def test_pause_and_resume(self) -> None:
        self.runtime.start()
        self.runtime.pause()
        self.assertTrue(self.runtime._paused)
        result = self.runtime.run_pipeline("financial")
        self.assertEqual(result.status, PipelineStatus.SKIPPED)
        self.runtime.resume()
        self.assertFalse(self.runtime._paused)
        result2 = self.runtime.run_pipeline("financial")
        self.assertNotEqual(result2.status, PipelineStatus.SKIPPED)

    def test_event_bus_running_after_start(self) -> None:
        self.runtime.start()
        self.assertTrue(self.runtime.bus._running)

    def test_events_emitted_on_pipeline_run(self) -> None:
        self.runtime.start()
        received = []
        self.runtime.bus.subscribe(
            lambda e: received.append(e),
            event_type=EventType.PIPELINE_COMPLETED,
        )
        self.runtime.run_pipeline("reporting")
        deadline = time.time() + 2.0
        while not received and time.time() < deadline:
            time.sleep(0.05)
        self.assertNonEmpty(received)

    def test_disabled_pipeline_skipped(self) -> None:
        cfg = RuntimeConfig.simulation()
        cfg.state.checkpoint_path = self.tmp_path("rt2", "cp.json")
        cfg.evolution.mode        = PipelineMode.DISABLED
        rt = NexusRuntime(config=cfg)
        rt.start()
        try:
            result = rt.run_pipeline("evolution")
            self.assertEqual(result.status, PipelineStatus.SKIPPED)
        finally:
            rt.stop()

    def test_scheduler_tasks_registered_after_start(self) -> None:
        self.runtime.start()
        tasks = self.runtime.pipeline_tasks()
        self.assertGreater(len(tasks), 0)

    def test_audit_chain_valid_after_pipelines(self) -> None:
        self.runtime.start()
        self.runtime.run_all_pipelines()
        ok = self.runtime.audit_chain_ok()
        self.assertTrue(ok)

    def test_stop_saves_checkpoint(self) -> None:
        self.runtime.start()
        self.runtime.run_pipeline("financial")
        self.runtime.stop()
        checkpoints = self.runtime.state.list_checkpoints()
        self.assertGreater(len(checkpoints), 0)


if __name__ == "__main__":
    unittest.main()
