"""
NEXUS Test Suite — Auto Evolution Module
Tests for: EvolutionRules, EvolutionEngine, SelfRepair, Optimizer,
and AutoEvolution facade (simulation/dry-run mode only).
"""

import os
import unittest

from conftest import NexusTestCase, CLEAN_PYTHON, SMELLY_PYTHON, INVALID_PYTHON

from auto_evolution.evolution_rules import (
    EvolutionRules, EvolutionPermission, EvolutionPolicy, RiskLevel, RuleViolation,
)

from auto_evolution.evolution_engine import EvolutionEngine
from auto_evolution.self_repair import SelfRepair
from auto_evolution.optimizer import Optimizer
from auto_evolution import AutoEvolution


# ---------------------------------------------------------------------------
# EvolutionRules
# ---------------------------------------------------------------------------

class TestEvolutionRules(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.rules = EvolutionRules()

    def test_default_allows_analyse(self) -> None:
        # check_permission(EvolutionPermission) — should not raise for ANALYSE
        self.rules.check_permission(EvolutionPermission.ANALYSE)

    def test_default_denies_mutate(self) -> None:
        with self.assertRaises(RuleViolation):
            self.rules.check_permission(EvolutionPermission.MUTATE)

    def test_check_permission_suggest_passes(self) -> None:
        self.rules.check_permission(EvolutionPermission.SUGGEST)

    def test_check_permission_delete_raises(self) -> None:
        with self.assertRaises(RuleViolation):
            self.rules.check_permission(EvolutionPermission.DELETE)

    def test_risk_level_string_values(self) -> None:
        levels = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        values = [r.value for r in levels]
        self.assertEqual(values, ["low", "medium", "high", "critical"])

    def test_is_dry_run_returns_bool(self) -> None:
        self.assertIsInstance(self.rules.is_dry_run(), bool)

    def test_snapshot_returns_dict_with_granted_permissions(self) -> None:
        snap = self.rules.snapshot()
        self.assertIsInstance(snap, dict)
        self.assertIn("granted_permissions", snap)

    def test_grant_and_revoke(self) -> None:
        self.rules.grant(EvolutionPermission.PATCH)
        self.rules.check_permission(EvolutionPermission.PATCH)   # should not raise
        self.rules.revoke(EvolutionPermission.PATCH)
        with self.assertRaises(RuleViolation):
            self.rules.check_permission(EvolutionPermission.PATCH)


# ---------------------------------------------------------------------------
# EvolutionEngine
# ---------------------------------------------------------------------------

class TestEvolutionEngine(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.engine = EvolutionEngine(base_dir=self.tmp)
        self.clean_file  = self.tmp_file("clean.py",  CLEAN_PYTHON)
        self.smelly_file = self.tmp_file("smelly.py", SMELLY_PYTHON)

    def test_analyse_clean_file_returns_list(self) -> None:
        result = self.engine.analyse_file(self.clean_file)
        self.assertIsInstance(result, list)

    def test_analyse_smelly_file_returns_list(self) -> None:
        result = self.engine.analyse_file(self.smelly_file)
        self.assertIsInstance(result, list)

    def test_run_cycle_returns_report(self) -> None:
        # run_cycle takes target_files (list of paths)
        report = self.engine.run_cycle(target_files=[self.clean_file])
        self.assertIsNotNone(report)

    def test_run_cycle_report_has_to_dict(self) -> None:
        report = self.engine.run_cycle(target_files=[self.clean_file])
        d = report.to_dict() if hasattr(report, "to_dict") else vars(report)
        self.assertIsInstance(d, dict)

    def test_stats_returns_dict(self) -> None:
        self.assertIsInstance(self.engine.stats(), dict)

    def test_history_initially_empty(self) -> None:
        engine = EvolutionEngine(base_dir=self.tmp)
        self.assertIsInstance(engine.history(), list)


# ---------------------------------------------------------------------------
# SelfRepair
# ---------------------------------------------------------------------------

class TestSelfRepair(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        snap_dir = self.tmp_subdir("snapshots")
        policy = EvolutionPolicy(
            granted_permissions={EvolutionPermission.ANALYSE, EvolutionPermission.SUGGEST,
                                 EvolutionPermission.REPAIR},
            allowed_path_patterns=["**"],
        )
        rules = EvolutionRules(policy=policy)
        self.repair = SelfRepair(rules=rules, snapshot_dir=snap_dir, base_dir=self.tmp)
        self.target = self.tmp_file("module.py", CLEAN_PYTHON)

    def test_snapshot_returns_object(self) -> None:
        result = self.repair.snapshot(self.target)
        self.assertIsNotNone(result)

    def test_check_integrity_valid_file(self) -> None:
        self.repair.snapshot(self.target)
        ok, msg = self.repair.check_integrity(self.target)
        self.assertTrue(ok, msg)

    def test_check_integrity_after_tamper(self) -> None:
        self.repair.snapshot(self.target)
        with open(self.target, "w") as fh:
            fh.write("TAMPERED\n")
        ok, msg = self.repair.check_integrity(self.target)
        self.assertFalse(ok)

    def test_check_syntax_valid_file(self) -> None:
        ok, msg = self.repair.check_syntax(self.target)
        self.assertTrue(ok, msg)

    def test_check_syntax_invalid_file(self) -> None:
        bad = self.tmp_file("bad.py", INVALID_PYTHON)
        ok, msg = self.repair.check_syntax(bad)
        self.assertFalse(ok)

    def test_restore_after_snapshot(self) -> None:
        self.repair.snapshot(self.target)
        with open(self.target, "w") as fh:
            fh.write("CORRUPTED\n")
        ok = self.repair.restore(self.target)
        self.assertTrue(ok)
        with open(self.target) as fh:
            content = fh.read()
        self.assertIn("def add", content)

    def test_list_snapshots_after_snapshot(self) -> None:
        self.repair.snapshot(self.target)
        snaps = self.repair.list_snapshots(self.target)
        self.assertIsInstance(snaps, list)
        self.assertGreater(len(snaps), 0)

    def test_stats_returns_dict(self) -> None:
        self.assertIsInstance(self.repair.stats(), dict)

    def test_auto_repair_valid_file(self) -> None:
        self.repair.snapshot(self.target)
        result = self.repair.auto_repair(self.target)
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------

class TestOptimizer(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.optimizer = Optimizer()

    def test_analyse_clean_file_returns_list(self) -> None:
        clean = self.tmp_file("clean.py", CLEAN_PYTHON)
        issues = self.optimizer.analyse_file(clean)
        self.assertIsInstance(issues, list)

    def test_analyse_smelly_file_finds_issues(self) -> None:
        smelly = self.tmp_file("smelly.py", SMELLY_PYTHON)
        issues = self.optimizer.analyse_file(smelly)
        self.assertIsInstance(issues, list)
        self.assertGreater(len(issues), 0,
                           "Expected optimizer to find issues in smelly code")

    def test_suggestion_has_required_fields(self) -> None:
        smelly = self.tmp_file("smelly.py", SMELLY_PYTHON)
        issues = self.optimizer.analyse_file(smelly)
        if issues:
            s = issues[0]
            self.assertTrue(hasattr(s, "category"))
            self.assertTrue(hasattr(s, "description"))
            self.assertTrue(hasattr(s, "risk"))

    def test_analyse_files_returns_report(self) -> None:
        clean = self.tmp_file("clean.py", CLEAN_PYTHON)
        report = self.optimizer.analyse_files([clean])
        self.assertIsNotNone(report)

    def test_top_suggestions_returns_list(self) -> None:
        smelly = self.tmp_file("smelly.py", SMELLY_PYTHON)
        suggestions = self.optimizer.top_suggestions([smelly], limit=5)
        self.assertIsInstance(suggestions, list)


# ---------------------------------------------------------------------------
# AutoEvolution facade (dry-run)
# ---------------------------------------------------------------------------

class TestAutoEvolutionFacade(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.ae = AutoEvolution()

    def test_start_does_not_raise(self) -> None:
        self.ae.start()

    def test_status_returns_dict(self) -> None:
        self.ae.start()
        s = self.ae.status()
        self.assertIsInstance(s, dict)
        self.assertIn("dry_run", s)

    def test_dry_run_by_default(self) -> None:
        self.ae.start()
        s = self.ae.status()
        self.assertTrue(s.get("dry_run", True))

    def test_enable_writes_clears_dry_run(self) -> None:
        self.ae.start()
        self.ae.enable_writes()
        self.assertFalse(self.ae.status()["dry_run"])
        self.ae.disable_writes()
        self.assertTrue(self.ae.status()["dry_run"])

    def test_run_cycle_with_file(self) -> None:
        self.ae.start()
        target = self.tmp_file("target.py", CLEAN_PYTHON)
        report = self.ae.run_cycle(target_files=[target])
        self.assertIsNotNone(report)

    def test_suggest_returns_list(self) -> None:
        self.ae.start()
        target = self.tmp_file("suggest.py", SMELLY_PYTHON)
        suggestions = self.ae.suggest(target)
        self.assertIsInstance(suggestions, list)

    def test_policy_returns_dict(self) -> None:
        s = self.ae.policy()
        self.assertIsInstance(s, dict)


if __name__ == "__main__":
    unittest.main()
