"""
NEXUS Reports package.

Generates, stores, and exports structured reports from all NEXUS subsystems.
Provides an append-only tamper-resistant audit log with SHA-256 hash chain.

Quick start:
    from reports import Reports

    r = Reports()
    r.start()

    # Financial report from raw data
    report = r.financial_from_dict({
        "portfolio": {
            "cash": 10000, "equity": 10500,
            "unrealised_pnl": 500, "realised_pnl": 0,
        }
    })
    print(report.to_json())

    # Audit log
    from reports import AuditEventType, AuditSeverity
    r.log_event(AuditEventType.AUTH_FAILURE, actor="user_x",
                action="login", severity=AuditSeverity.WARNING)
    ok, errors = r.verify_audit_chain()

    # With NexusCore
    from core import get_core
    r = Reports.from_core(get_core())
    r.start()
"""

# Base primitives
from .report_builder import (
    BaseReport,
    Metric,
    MetricBlock,
    ReportSection,
    ReportSeverity,
    ReportStatus,
    ReportTable,
    TableRow,
)

# Domain reports
from .financial_reports    import FinancialReport
from .intelligence_reports import IntelligenceReport
from .evolution_reports    import EvolutionReport
from .multi_ia_reports     import MultiIAReport

# Audit log
from .audit_log import (
    AuditEntry,
    AuditEventType,
    AuditLog,
    AuditSeverity,
    ViolationLog,
)

# Facade
from .reports import Reports, ReportsConfig

__all__ = [
    # Builder primitives
    "BaseReport", "Metric", "MetricBlock", "ReportSection",
    "ReportSeverity", "ReportStatus", "ReportTable", "TableRow",
    # Domain reports
    "FinancialReport", "IntelligenceReport", "EvolutionReport", "MultiIAReport",
    # Audit log
    "AuditEntry", "AuditEventType", "AuditLog", "AuditSeverity", "ViolationLog",
    # Facade
    "Reports", "ReportsConfig",
]
