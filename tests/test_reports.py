"""
NEXUS Test Suite — Reports Module
Tests for: BaseReport, MetricBlock, ReportTable, FinancialReport,
IntelligenceReport, EvolutionReport, MultiIAReport,
AuditLog (hash chain integrity, tamper detection), ViolationLog,
and Reports facade.
"""

import json
import os
import unittest

from conftest import NexusTestCase, make_equity_curve

from reports.report_builder import (
    BaseReport, MetricBlock, ReportSection, ReportSeverity,
    ReportStatus, ReportTable, Metric,
)
from reports.financial_reports import FinancialReport
from reports.intelligence_reports import IntelligenceReport
from reports.evolution_reports import EvolutionReport
from reports.multi_ia_reports import MultiIAReport
from reports.audit_log import (
    AuditLog, AuditEntry, AuditEventType, AuditSeverity, ViolationLog,
)
from reports import Reports, ReportsConfig


# ---------------------------------------------------------------------------
# BaseReport / ReportBuilder primitives
# ---------------------------------------------------------------------------

class TestMetricBlock(NexusTestCase):

    def test_add_and_to_dict(self) -> None:
        blk = MetricBlock("Performance")
        blk.add("PnL", 1234.56, "USD")
        blk.add("Drawdown", 5.2, "%", severity=ReportSeverity.WARNING)
        d = blk.to_dict()
        self.assertEqual(d["title"], "Performance")
        self.assertEqual(len(d["metrics"]), 2)

    def test_metric_severity_stored(self) -> None:
        blk = MetricBlock("Risk")
        blk.add("Breach", True, severity=ReportSeverity.CRITICAL)
        self.assertEqual(blk.metrics[0].severity, ReportSeverity.CRITICAL)


class TestReportTable(NexusTestCase):

    def test_add_rows_and_to_dict(self) -> None:
        tbl = ReportTable("Trades", headers=["Symbol", "Side", "PnL"])
        tbl.add_row("BTC", "BUY", 150.0)
        tbl.add_row("ETH", "SELL", -30.0)
        d = tbl.to_dict()
        self.assertEqual(len(d["rows"]), 2)
        self.assertEqual(d["headers"], ["Symbol", "Side", "PnL"])

    def test_empty_table_serializes(self) -> None:
        tbl = ReportTable("Empty", headers=["A", "B"])
        d = tbl.to_dict()
        self.assertEqual(d["rows"], [])


class ConcreteReport(BaseReport):
    report_type = "test"


class TestBaseReport(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.report = ConcreteReport("Test Report", description="Unit test report")

    def test_initial_status_draft(self) -> None:
        self.assertEqual(self.report.status, ReportStatus.DRAFT)

    def test_finalise_changes_status(self) -> None:
        self.report.finalise()
        self.assertEqual(self.report.status, ReportStatus.FINAL)

    def test_to_dict_has_required_keys(self) -> None:
        d = self.report.to_dict()
        self.assertDictHasKeys(d,
            "report_id", "report_type", "title", "status",
            "sections", "created_at",
        )

    def test_to_json_is_valid_json(self) -> None:
        blob = self.report.to_json()
        parsed = json.loads(blob)
        self.assertEqual(parsed["title"], "Test Report")

    def test_add_section(self) -> None:
        section = self.report._new_section("Section 1", body="Some content")
        self.assertEqual(len(self.report.sections), 1)
        self.assertEqual(self.report.sections[0].title, "Section 1")

    def test_section_with_metric_block(self) -> None:
        section = self.report._new_section("Metrics")
        blk = MetricBlock("KPIs")
        blk.add("Value", 42)
        section.add_metric_block(blk)
        d = self.report.to_dict()
        self.assertEqual(len(d["sections"][0]["metric_blocks"]), 1)

    def test_summary_returns_dict(self) -> None:
        s = self.report.summary()
        self.assertDictHasKeys(s, "report_id", "report_type", "title")


# ---------------------------------------------------------------------------
# FinancialReport
# ---------------------------------------------------------------------------

class TestFinancialReport(NexusTestCase):

    def _data(self, equity: float = 10500.0, unrealised: float = 500.0) -> dict:
        return {
            "portfolio": {
                "cash":           10000.0,
                "equity":         equity,
                "unrealised_pnl": unrealised,
                "realised_pnl":   200.0,
                "equity_curve":   make_equity_curve(20, 10000.0),
                "daily_returns":  [0.001, 0.002, -0.001, 0.003, 0.0015] * 4,
            },
            "risk": {
                "daily_loss":     50.0,
                "current_drawdown": 0.02,
            },
        }

    def test_from_dict_creates_report(self) -> None:
        report = FinancialReport.from_dict(self._data())
        self.assertEqual(report.status, ReportStatus.FINAL)
        self.assertNonEmpty(report.sections)

    def test_report_has_portfolio_section(self) -> None:
        report = FinancialReport.from_dict(self._data())
        titles = [s.title for s in report.sections]
        self.assertTrue(any("Portfolio" in t for t in titles))

    def test_serializable_to_json(self) -> None:
        report = FinancialReport.from_dict(self._data())
        blob   = report.to_json()
        parsed = json.loads(blob)
        self.assertEqual(parsed["report_type"], "financial")

    def test_critical_drawdown_flagged(self) -> None:
        data = self._data()
        data["portfolio"]["equity_curve"] = [10000.0, 8000.0, 7000.0]
        report = FinancialReport.from_dict(data)
        # High drawdown should produce WARNING or CRITICAL section
        severities = [s.severity for s in report.sections]
        self.assertIn(ReportSeverity.CRITICAL, severities)

    def test_add_trade_summary(self) -> None:
        report = FinancialReport.from_dict(self._data())
        trades = [
            {"trade_id": "t1", "symbol": "BTC", "side": "BUY",
             "entry_price": 100.0, "exit_price": 110.0, "pnl": 10.0},
            {"trade_id": "t2", "symbol": "ETH", "side": "SELL",
             "entry_price": 200.0, "exit_price": 190.0, "pnl": 10.0},
        ]
        report.add_trade_summary(trades)
        titles = [s.title for s in report.sections]
        self.assertTrue(any("Trade" in t for t in titles))


# ---------------------------------------------------------------------------
# IntelligenceReport
# ---------------------------------------------------------------------------

class TestIntelligenceReport(NexusTestCase):

    def _data(self) -> dict:
        return {
            "patterns": {
                "detected_patterns": [
                    {"type": "breakout", "symbol": "BTC",
                     "confidence": 0.85, "detected_at": "2026-01-01"},
                    {"type": "anomaly_price", "symbol": "ETH",
                     "confidence": 0.92, "detected_at": "2026-01-01"},
                ]
            },
            "sentiment": {
                "average_score": -0.45,
                "articles_analysed": 12,
                "bullish_count": 3,
                "bearish_count": 9,
                "risk_hits": 2,
            },
        }

    def test_from_dict_creates_report(self) -> None:
        report = IntelligenceReport.from_dict(self._data())
        self.assertEqual(report.status, ReportStatus.FINAL)

    def test_patterns_section_present(self) -> None:
        report = IntelligenceReport.from_dict(self._data())
        titles = [s.title for s in report.sections]
        self.assertTrue(any("Pattern" in t for t in titles))

    def test_critical_anomaly_raises_severity(self) -> None:
        report = IntelligenceReport.from_dict(self._data())
        severities = [s.severity for s in report.sections]
        self.assertIn(ReportSeverity.CRITICAL, severities)


# ---------------------------------------------------------------------------
# AuditLog — hash chain integrity
# ---------------------------------------------------------------------------

class TestAuditLog(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.log_path = self.tmp_path("audit.jsonl")
        self.log = AuditLog(file_path=self.log_path)

    def test_append_returns_entry(self) -> None:
        entry = self.log.append(AuditEventType.INFO, actor="system", action="test")
        self.assertIsInstance(entry, AuditEntry)
        self.assertGreater(len(entry.entry_hash), 0)

    def test_entry_hash_valid(self) -> None:
        entry = self.log.append(AuditEventType.INFO, actor="a", action="b")
        self.assertTrue(entry.verify(), "Entry hash should be valid after creation")

    def test_chain_integrity_after_multiple_entries(self) -> None:
        for i in range(10):
            self.log.append(AuditEventType.INFO, actor=f"actor_{i}", action="action")
        ok, errors = self.log.verify_chain()
        self.assertTrue(ok, f"Chain should be intact: {errors}")
        self.assertEqual(errors, [])

    def test_chain_linkage(self) -> None:
        e1 = self.log.append(AuditEventType.INFO, actor="a", action="first")
        e2 = self.log.append(AuditEventType.INFO, actor="a", action="second")
        self.assertEqual(e2.prev_hash, e1.entry_hash)

    def test_genesis_prev_hash_is_zeros(self) -> None:
        e = self.log.append(AuditEventType.INFO, actor="a", action="genesis")
        self.assertEqual(e.prev_hash, "0" * 64)

    def test_tamper_detection_modified_content(self) -> None:
        self.log.append(AuditEventType.AUTH_SUCCESS, actor="user", action="login")
        self.log.append(AuditEventType.INFO, actor="user", action="read")
        # Tamper with first entry
        self.log._entries[0].outcome = "TAMPERED"
        ok, errors = self.log.verify_chain()
        self.assertFalse(ok)
        self.assertNonEmpty(errors)

    def test_tamper_detection_broken_chain(self) -> None:
        self.log.append(AuditEventType.INFO, actor="a", action="1")
        self.log.append(AuditEventType.INFO, actor="a", action="2")
        self.log.append(AuditEventType.INFO, actor="a", action="3")
        # Break the chain link
        self.log._entries[1].prev_hash = "a" * 64
        ok, errors = self.log.verify_chain()
        self.assertFalse(ok)

    def test_persistence_to_jsonl(self) -> None:
        self.log.append(AuditEventType.SYSTEM_START, actor="runtime", action="start")
        self.log.append(AuditEventType.SYSTEM_STOP,  actor="runtime", action="stop")
        self.assertTrue(os.path.isfile(self.log_path))
        with open(self.log_path) as fh:
            lines = [l for l in fh if l.strip()]
        self.assertEqual(len(lines), 2)

    def test_load_from_file(self) -> None:
        self.log.append(AuditEventType.INFO, actor="a", action="persist")
        # New instance loads from same file
        log2 = AuditLog(file_path=self.log_path, load_existing=True)
        self.assertGreater(log2.count(), 0)

    def test_query_by_event_type(self) -> None:
        self.log.append(AuditEventType.AUTH_SUCCESS, actor="u", action="login")
        self.log.append(AuditEventType.AUTH_FAILURE, actor="u", action="login")
        hits = self.log.query(event_type=AuditEventType.AUTH_FAILURE)
        self.assertEqual(len(hits), 1)

    def test_query_by_actor(self) -> None:
        self.log.append(AuditEventType.INFO, actor="alice", action="read")
        self.log.append(AuditEventType.INFO, actor="bob",   action="read")
        hits = self.log.query(actor="alice")
        self.assertEqual(len(hits), 1)

    def test_stats_returns_dict(self) -> None:
        self.log.append(AuditEventType.VIOLATION, actor="x", action="bad")
        stats = self.log.stats()
        self.assertDictHasKeys(stats, "total_entries", "by_event_type", "by_severity")

    def test_to_list_and_json(self) -> None:
        self.log.append(AuditEventType.INFO, actor="a", action="test")
        lst = self.log.to_list()
        self.assertIsInstance(lst, list)
        blob = self.log.to_json()
        parsed = json.loads(blob)
        self.assertIsInstance(parsed, list)


# ---------------------------------------------------------------------------
# ViolationLog
# ---------------------------------------------------------------------------

class TestViolationLog(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.vlog = ViolationLog(file_path=self.tmp_path("violations.jsonl"))

    def test_record_violation(self) -> None:
        entry = self.vlog.record_violation(
            actor="profit_engine", code="RISK_BREACH",
            detail="Max drawdown exceeded",
        )
        self.assertEqual(entry.event_type, AuditEventType.VIOLATION)
        self.assertEqual(entry.severity, AuditSeverity.WARNING)

    def test_record_critical(self) -> None:
        entry = self.vlog.record_critical(
            actor="runtime", action="kill_switch",
            detail="Emergency stop triggered",
        )
        self.assertEqual(entry.severity, AuditSeverity.CRITICAL)

    def test_chain_valid_after_violations(self) -> None:
        self.vlog.record_violation("a", "CODE_1")
        self.vlog.record_violation("b", "CODE_2")
        self.vlog.record_critical("c", "emergency")
        ok, errors = self.vlog.verify_chain()
        self.assertTrue(ok, f"Chain errors: {errors}")


# ---------------------------------------------------------------------------
# Reports facade
# ---------------------------------------------------------------------------

class TestReportsFacade(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        cfg = ReportsConfig(
            audit_log_path=self.tmp_path("audit_chain.jsonl"),
            auto_export_json=False,
        )
        self.reports = Reports(cfg)
        self.reports.start()

    def tearDown(self) -> None:
        self.reports.stop()
        super().tearDown()

    def test_financial_from_dict(self) -> None:
        report = self.reports.financial_from_dict(
            {"portfolio": {"cash": 10000.0, "equity": 10200.0,
                           "unrealised_pnl": 200.0, "realised_pnl": 0.0}}
        )
        self.assertIsNotNone(report)
        self.assertEqual(report.report_type, "financial")

    def test_intelligence_from_dict(self) -> None:
        report = self.reports.intelligence_from_dict({"sentiment": {"average_score": 0.2}})
        self.assertEqual(report.report_type, "intelligence")

    def test_evolution_from_dict(self) -> None:
        report = self.reports.evolution_from_dict({})
        self.assertEqual(report.report_type, "evolution")

    def test_multi_ia_from_dict(self) -> None:
        report = self.reports.multi_ia_from_dict({})
        self.assertEqual(report.report_type, "multi_ia")

    def test_report_cached_and_retrievable(self) -> None:
        report = self.reports.financial_from_dict({"portfolio": {}})
        fetched = self.reports.get(report.report_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.report_id, report.report_id)

    def test_list_reports(self) -> None:
        self.reports.financial_from_dict({})
        listing = self.reports.list_reports()
        self.assertGreater(len(listing), 0)

    def test_log_violation_adds_audit_entry(self) -> None:
        before = self.reports.audit.count()
        self.reports.log_violation("actor_x", "TEST_VIOLATION", "test detail")
        after = self.reports.audit.count()
        self.assertGreater(after, before)

    def test_verify_audit_chain_passes(self) -> None:
        self.reports.log_event(AuditEventType.INFO, actor="test", action="unit_test")
        ok, errors = self.reports.verify_audit_chain()
        self.assertTrue(ok, f"Chain errors: {errors}")

    def test_export_json(self) -> None:
        report   = self.reports.financial_from_dict({})
        out_dir  = self.tmp_subdir("exports")
        path     = self.reports.export_json(report, directory=out_dir)
        self.assertTrue(os.path.isfile(path))
        with open(path) as fh:
            parsed = json.load(fh)
        self.assertEqual(parsed["report_type"], "financial")

    def test_status_returns_dict(self) -> None:
        status = self.reports.status()
        self.assertDictHasKeys(status, "running", "cached_reports", "audit")


if __name__ == "__main__":
    unittest.main()
