"""
NEXUS Reports — Facade
Single entry-point that wires all report types, the audit log,
and NexusCore integration. Generates, caches, and exports reports.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type

from .audit_log import AuditEventType, AuditLog, AuditSeverity, ViolationLog
from .evolution_reports import EvolutionReport
from .financial_reports import FinancialReport
from .intelligence_reports import IntelligenceReport
from .multi_ia_reports import MultiIAReport
from .report_builder import BaseReport, ReportSeverity


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ReportsConfig:
    """Runtime configuration for the Reports facade."""
    audit_log_path:      str  = "logs/audit_chain.jsonl"
    report_export_dir:   str  = "reports/exports"
    auto_export_json:    bool = False   # write each report to disk when finalised
    max_cached_reports:  int  = 50
    enable_audit_log:    bool = True


# ---------------------------------------------------------------------------
# Reports facade
# ---------------------------------------------------------------------------

class Reports:
    """
    Central reporting hub for NEXUS.

    Generates domain reports (financial, intelligence, evolution, multi_ia),
    maintains an append-only tamper-resistant audit log, and optionally
    exports reports to JSON files.

    Usage (standalone):
        from reports import Reports
        r = Reports()
        r.start()
        report = r.financial_from_dict({"portfolio": {...}})
        print(report.to_json())

    Usage (with NexusCore):
        from core import get_core
        r = Reports.from_core(get_core())
        r.start()
    """

    def __init__(self, config: Optional[ReportsConfig] = None) -> None:
        self._config   = config or ReportsConfig()
        self._running  = False
        self._lock     = threading.RLock()

        # Core integration handles
        self._logger   = None
        self._memory   = None
        self._security = None

        # Report cache: report_id → BaseReport
        self._cache: Dict[str, BaseReport] = {}

        # Audit log
        self.audit: AuditLog = (
            ViolationLog(
                file_path=self._config.audit_log_path,
                load_existing=True,
            )
            if self._config.enable_audit_log
            else AuditLog()
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def from_core(cls, core: Any, config: Optional[ReportsConfig] = None) -> "Reports":
        """Create a Reports instance wired to a running NexusCore."""
        instance = cls(config)
        instance._logger   = core.logger
        instance._memory   = core.memory
        instance._security = core.security
        return instance

    def start(self) -> None:
        self._running = True
        self.audit.append(
            AuditEventType.SYSTEM_START,
            actor="reports",
            action="start",
            outcome="Reports subsystem started.",
            severity=AuditSeverity.INFO,
        )
        self._log("reports", "Reports subsystem started.")

    def stop(self) -> None:
        self._running = False
        self.audit.append(
            AuditEventType.SYSTEM_STOP,
            actor="reports",
            action="stop",
            outcome="Reports subsystem stopped.",
            severity=AuditSeverity.INFO,
        )
        self._log("reports", "Reports subsystem stopped.")

    # ------------------------------------------------------------------
    # Financial reports
    # ------------------------------------------------------------------

    def financial_from_engine(
        self,
        engine:       Any,
        period_label: str = "current",
    ) -> FinancialReport:
        report = FinancialReport.from_engine(engine, period_label=period_label)
        self._store(report)
        return report

    def financial_from_dict(
        self,
        data:         Dict[str, Any],
        period_label: str = "snapshot",
    ) -> FinancialReport:
        report = FinancialReport.from_dict(data, period_label=period_label)
        self._store(report)
        return report

    # ------------------------------------------------------------------
    # Intelligence reports
    # ------------------------------------------------------------------

    def intelligence_from_engine(
        self,
        web_intelligence: Any,
        symbol:           str = "MARKET",
    ) -> IntelligenceReport:
        report = IntelligenceReport.from_intelligence(web_intelligence, symbol=symbol)
        self._store(report)
        return report

    def intelligence_from_dict(
        self,
        data:         Dict[str, Any],
        period_label: str = "snapshot",
    ) -> IntelligenceReport:
        report = IntelligenceReport.from_dict(data, period_label=period_label)
        self._store(report)
        return report

    # ------------------------------------------------------------------
    # Evolution reports
    # ------------------------------------------------------------------

    def evolution_from_engine(
        self,
        auto_evolution: Any,
        cycle_limit:    int = 20,
    ) -> EvolutionReport:
        report = EvolutionReport.from_evolution(auto_evolution, cycle_limit=cycle_limit)
        self._store(report)
        return report

    def evolution_from_dict(
        self,
        data:         Dict[str, Any],
        period_label: str = "snapshot",
    ) -> EvolutionReport:
        report = EvolutionReport.from_dict(data, period_label=period_label)
        self._store(report)
        return report

    # ------------------------------------------------------------------
    # Multi-IA reports
    # ------------------------------------------------------------------

    def multi_ia_from_engine(
        self,
        multi_ia:      Any,
        history_limit: int = 20,
    ) -> MultiIAReport:
        report = MultiIAReport.from_multi_ia(multi_ia, history_limit=history_limit)
        self._store(report)
        return report

    def multi_ia_from_dict(
        self,
        data:         Dict[str, Any],
        period_label: str = "snapshot",
    ) -> MultiIAReport:
        report = MultiIAReport.from_dict(data, period_label=period_label)
        self._store(report)
        return report

    # ------------------------------------------------------------------
    # Audit helpers
    # ------------------------------------------------------------------

    def log_event(
        self,
        event_type: AuditEventType,
        actor:      str,
        action:     str,
        outcome:    str = "",
        target:     str = "",
        severity:   AuditSeverity = AuditSeverity.INFO,
        detail:     Optional[Dict[str, Any]] = None,
    ) -> None:
        self.audit.append(
            event_type=event_type,
            actor=actor,
            action=action,
            target=target,
            outcome=outcome,
            severity=severity,
            detail=detail or {},
        )

    def log_violation(
        self,
        actor:  str,
        code:   str,
        detail: str = "",
        target: str = "",
    ) -> None:
        if isinstance(self.audit, ViolationLog):
            self.audit.record_violation(actor=actor, code=code,
                                        detail=detail, target=target)
        else:
            self.log_event(AuditEventType.VIOLATION, actor=actor,
                           action="violation", outcome=code,
                           target=target, severity=AuditSeverity.WARNING,
                           detail={"code": code, "detail": detail})

    def verify_audit_chain(self) -> tuple[bool, List[str]]:
        """Verify tamper-resistance of the audit log hash chain."""
        return self.audit.verify_chain()

    # ------------------------------------------------------------------
    # Report management
    # ------------------------------------------------------------------

    def get(self, report_id: str) -> Optional[BaseReport]:
        with self._lock:
            return self._cache.get(report_id)

    def list_reports(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [r.summary() for r in self._cache.values()]

    def export_json(
        self,
        report:    BaseReport,
        directory: Optional[str] = None,
    ) -> str:
        """Write report JSON to disk. Returns the file path."""
        out_dir = directory or self._config.report_export_dir
        os.makedirs(out_dir, exist_ok=True)
        filename = f"{report.report_type}_{report.report_id}.json"
        path     = os.path.join(out_dir, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(report.to_json())
        self._log("reports", f"Report exported: {path}")
        return path

    def export_all_json(self, directory: Optional[str] = None) -> List[str]:
        """Export all cached reports to JSON files."""
        with self._lock:
            reports = list(self._cache.values())
        return [self.export_json(r, directory) for r in reports]

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        with self._lock:
            cached = len(self._cache)
        return {
            "running":        self._running,
            "cached_reports": cached,
            "audit":          self.audit.stats(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store(self, report: BaseReport) -> None:
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self._config.max_cached_reports:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[report.report_id] = report

        if self._config.auto_export_json:
            try:
                self.export_json(report)
            except Exception:
                pass

        self._log("reports",
                  f"Report stored: type={report.report_type} id={report.report_id}")

    def _log(self, module: str, message: str, level: str = "info", **kw: Any) -> None:
        if self._logger:
            getattr(self._logger, level, self._logger.info)(module, message, **kw)
