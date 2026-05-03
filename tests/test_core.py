"""
NEXUS Test Suite — Core Module
Tests for: NexusLogger, SecurityManager, MemoryManager,
TaskManager, and CommandInterpreter.
"""

import os
import time
import unittest

from conftest import NexusTestCase

from core.logger import NexusLogger, LogLevel
from core.security_manager import SecurityManager, SecurityPolicy, SecurityViolation
from core.memory_manager import MemoryManager, ShortTermMemory, LongTermMemory
from core.task_manager import TaskManager, Task, Priority
from core.command_interpreter import CommandInterpreter, CommandResult


# ---------------------------------------------------------------------------
# NexusLogger
# ---------------------------------------------------------------------------

class TestNexusLogger(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        NexusLogger._instance = None   # reset singleton so each test gets a fresh instance
        self.log_dir = self.tmp_subdir("logs")
        self.logger = NexusLogger(log_dir=self.log_dir)

    def tearDown(self) -> None:
        NexusLogger._instance = None
        super().tearDown()

    def test_info_does_not_raise(self) -> None:
        self.logger.info("test", "This is an info message.")

    def test_warning_does_not_raise(self) -> None:
        self.logger.warning("test", "This is a warning.")

    def test_error_does_not_raise(self) -> None:
        self.logger.error("test", "This is an error.")

    def test_critical_does_not_raise(self) -> None:
        self.logger.critical("test", "This is critical.")

    def test_audit_does_not_raise(self) -> None:
        self.logger.audit("user_a", "login", "nexus", "success")

    def test_log_file_created(self) -> None:
        self.logger.info("test", "writing to file")
        log_files = os.listdir(self.log_dir)
        self.assertNonEmpty(log_files)

    def test_set_level(self) -> None:
        self.logger.set_level(LogLevel.WARNING)
        self.logger.info("test", "This should be filtered.")

    def test_extra_kwargs_accepted(self) -> None:
        self.logger.info("module", "Message with metadata", user="alice", value=42)


# ---------------------------------------------------------------------------
# SecurityManager
# ---------------------------------------------------------------------------

class TestSecurityManager(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.policy = SecurityPolicy()
        self.sm = SecurityManager(self.policy)

    def test_generate_token_returns_string(self) -> None:
        token = self.sm.generate_token()
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 10)

    def test_valid_token_authenticates(self) -> None:
        token = self.sm.generate_token()
        result = self.sm.authenticate(token)
        self.assertTrue(result)

    def test_block_and_unblock_actor(self) -> None:
        self.sm.block_actor("evil_bot")
        self.assertTrue(self.sm.is_blocked("evil_bot"))
        self.sm.unblock_actor("evil_bot")
        self.assertFalse(self.sm.is_blocked("evil_bot"))

    def test_is_blocked_unknown_actor(self) -> None:
        self.assertFalse(self.sm.is_blocked("unknown_actor"))

    def test_validate_input_clean(self) -> None:
        result = self.sm.validate_input("Hello, world!")
        self.assertIsInstance(result, str)

    def test_validate_command_clean(self) -> None:
        result = self.sm.validate_command("nexus status")
        self.assertIsInstance(result, str)

    def test_violations_returns_list(self) -> None:
        v = self.sm.violations()
        self.assertIsInstance(v, list)

    def test_rate_limit_status_returns_dict(self) -> None:
        status = self.sm.rate_limit_status("actor_a")
        self.assertIsInstance(status, dict)


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------

class TestShortTermMemory(NexusTestCase):

    def test_set_and_get(self) -> None:
        mem = ShortTermMemory(capacity=10)
        mem.set("key1", {"value": 42})
        result = mem.get("key1")
        self.assertEqual(result["value"], 42)

    def test_get_missing_returns_none(self) -> None:
        mem = ShortTermMemory(capacity=10)
        self.assertIsNone(mem.get("nonexistent"))

    def test_capacity_evicts_oldest(self) -> None:
        mem = ShortTermMemory(capacity=3)
        for i in range(5):
            mem.set(f"key{i}", i)
        self.assertIsNone(mem.get("key0"))
        self.assertIsNone(mem.get("key1"))
        self.assertIsNotNone(mem.get("key4"))

    def test_delete(self) -> None:
        mem = ShortTermMemory(capacity=10)
        mem.set("k", "v")
        mem.delete("k")
        self.assertIsNone(mem.get("k"))

    def test_stats_returns_dict(self) -> None:
        mem = ShortTermMemory(capacity=10)
        mem.set("x", 1)
        self.assertIsInstance(mem.stats(), dict)


class TestLongTermMemory(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.store_path = self.tmp_path("long_term.json")
        self.mem = LongTermMemory(storage_path=self.store_path)

    def test_set_and_get(self) -> None:
        self.mem.set("fact1", "The sky is blue")
        self.assertEqual(self.mem.get("fact1"), "The sky is blue")

    def test_persistence_across_instances(self) -> None:
        self.mem.set("persistent_key", {"data": 99})
        mem2 = LongTermMemory(storage_path=self.store_path)
        self.assertEqual(mem2.get("persistent_key"), {"data": 99})

    def test_delete_removes_entry(self) -> None:
        self.mem.set("temp", "value")
        self.mem.delete("temp")
        self.assertIsNone(self.mem.get("temp"))


class TestMemoryManager(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.mm = MemoryManager(
            stm_capacity=20,
            ltm_path=self.tmp_path("memory.json"),
        )

    def test_remember_and_recall_short(self) -> None:
        self.mm.remember("k", "v")
        self.assertEqual(self.mm.recall("k"), "v")

    def test_remember_long_term(self) -> None:
        self.mm.remember("lk", {"x": 1}, permanent=True)
        self.assertEqual(self.mm.recall("lk"), {"x": 1})

    def test_stats_returns_dict(self) -> None:
        stats = self.mm.stats()
        self.assertIsInstance(stats, dict)


# ---------------------------------------------------------------------------
# TaskManager
# ---------------------------------------------------------------------------

class TestTaskManager(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.tm = TaskManager(max_workers=2)

    def test_submit_task_returns_task(self) -> None:
        task = self.tm.submit(lambda: None, name="noop")
        self.assertIsInstance(task, Task)
        self.assertGreater(len(task.task_id), 0)

    def test_task_executed(self) -> None:
        results = []

        def work():
            results.append(42)

        self.tm.submit(work, name="work")
        deadline = time.time() + 2.0
        while not results and time.time() < deadline:
            time.sleep(0.05)
        self.assertIn(42, results)

    def test_stats_returns_dict(self) -> None:
        stats = self.tm.stats()
        self.assertIsInstance(stats, dict)
        self.assertIn("total_tasks", stats)

    def test_priority_task(self) -> None:
        task = self.tm.submit(
            lambda: None, name="high_prio",
            priority=Priority.HIGH,
        )
        self.assertIsInstance(task, Task)


# ---------------------------------------------------------------------------
# CommandInterpreter
# ---------------------------------------------------------------------------

class TestCommandInterpreter(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.ci = CommandInterpreter()

    def test_parse_simple_command(self) -> None:
        parsed = self.ci.parse("nexus status")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.namespace, "nexus")
        self.assertEqual(parsed.action, "status")

    def test_parse_with_flags(self) -> None:
        parsed = self.ci.parse("nexus diagnostics --verbose")
        self.assertIsNotNone(parsed)
        self.assertIn("verbose", parsed.flags)

    def test_parse_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.ci.parse("")

    def test_register_and_execute_handler(self) -> None:
        called = []

        def handle_ping(cmd):
            called.append(True)
            return CommandResult(success=True, command="nexus ping", output="pong")

        self.ci.register("nexus", "ping", handle_ping)
        result = self.ci.execute("nexus ping")
        self.assertTrue(result.success)
        self.assertNonEmpty(called)

    def test_unknown_command_returns_failure(self) -> None:
        result = self.ci.execute("nexus unknowncmd_xyz")
        self.assertFalse(result.success)

    def test_command_with_subaction(self) -> None:
        parsed = self.ci.parse("nexus module start")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.action, "module")


if __name__ == "__main__":
    unittest.main()
