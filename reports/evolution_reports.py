"""
NEXUS Reports — Evolution Reports
Structured reports from auto_evolution data:
evolution cycles, generated patches, rollbacks, optimizer findings,
mutation A/B tests, and self-repair events.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .report_builder import (
    BaseReport, MetricBlock, ReportSection, ReportSeverity,
    ReportTable,
)


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

def _risk_severity(risk_level: str) -> ReportSeverity:
    mapping = {
        "low":      ReportSeverity.INFO,
        "medium":   ReportSeverity.WARNING,
        "high":     ReportSeverity.WARNING,
        "critical": ReportSeverity.CRITICAL,
    }
    return mapping.get(risk_level.lower(), ReportSeverity.INFO)


# ---------------------------------------------------------------------------
# EvolutionReport
# ---------------------------------------------------------------------------

class EvolutionReport(BaseReport):
    """
    Report covering the NEXUS auto-evolution subsystem:
    analysis cycles, patches, rollbacks, and mutation experiments.
    """

    report_type = "evolution"

    def __init__(self, title: str = "Auto-Evolution Report") -> None:
        super().__init__(
            title=title,
            description="Cycle summaries, patches, rollbacks, optimizer findings.",
        )

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_evolution(
        cls,
        auto_evolution: Any,
        cycle_limit:    int = 20,
    ) -> "EvolutionReport":
        """Build from a live AutoEvolution facade."""
        report = cls()
        try:
            status = auto_evolution.status()
        except Exception as exc:
            report._meta["engine_error"] = str(exc)
            report._new_section("Error", body=str(exc), severity=ReportSeverity.CRITICAL)
            return report.finalise()

        report._build_overview_section(status)
        report._build_cycles_section(status.get("recent_cycles", []), cycle_limit)
        report._build_mutations_section(status.get("mutations", {}))
        report._build_repairs_section(status.get("repairs",   []))
        return report.finalise()

    @classmethod
    def from_dict(
        cls,
        data:         Dict[str, Any],
        period_label: str = "snapshot",
    ) -> "EvolutionReport":
        report = cls(title=f"Evolution Report — {period_label}")
        report._build_overview_section(data)
        report._build_cycles_section(data.get("cycles", data.get("recent_cycles", [])))
        report._build_patches_table(data.get("patches", []))
        report._build_mutations_section(data.get("mutations", {}))
        report._build_repairs_section(data.get("repairs", []))
        return report.finalise()

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_overview_section(self, status: Dict[str, Any]) -> None:
        section = self._new_section("Evolution Overview")

        engine_stats = status.get("engine", status)
        blk = MetricBlock("Engine Stats")
        blk.add("Write Mode",       "enabled" if status.get("writes_enabled") else "dry-run",
                severity=ReportSeverity.WARNING if status.get("writes_enabled") else ReportSeverity.INFO)
        blk.add("Total Cycles",     engine_stats.get("total_cycles",    0))
        blk.add("Patches Generated", engine_stats.get("patches_generated", 0))
        blk.add("Patches Applied",  engine_stats.get("patches_applied",    0))
        blk.add("Files Analysed",   engine_stats.get("files_analysed",     0))

        repair_stats = status.get("self_repair", {})
        blk.add("Snapshots",        repair_stats.get("total_snapshots",  0))
        blk.add("Rollbacks",        repair_stats.get("total_rollbacks",  0),
                severity=ReportSeverity.WARNING if int(repair_stats.get("total_rollbacks", 0)) > 0
                          else ReportSeverity.INFO)

        section.add_metric_block(blk)

        optimizer_stats = status.get("optimizer", {})
        if optimizer_stats:
            blk2 = MetricBlock("Optimizer")
            blk2.add("Total Runs",    optimizer_stats.get("total_runs",   0))
            blk2.add("Issues Found",  optimizer_stats.get("issues_found", 0),
                     severity=ReportSeverity.WARNING if int(optimizer_stats.get("issues_found", 0)) > 0
                               else ReportSeverity.INFO)
            section.add_metric_block(blk2)

    def _build_cycles_section(
        self,
        cycles:    List[Dict[str, Any]],
        limit:     int = 20,
    ) -> None:
        if not cycles:
            return
        section = self._new_section("Recent Evolution Cycles")
        tbl = ReportTable(
            title="Cycles",
            headers=["Cycle ID", "Status", "Files", "Patches", "Applied", "Score", "Duration (s)"],
        )
        for cycle in cycles[-limit:]:
            tbl.add_row(
                str(cycle.get("cycle_id",        "—"))[:10],
                cycle.get("status",          "—"),
                cycle.get("files_analysed",   0),
                cycle.get("patches_generated", 0),
                cycle.get("patches_applied",   0),
                round(float(cycle.get("score", 0)), 4),
                round(float(cycle.get("duration_s", 0)), 2),
            )
        section.add_table(tbl)

    def _build_patches_table(self, patches: List[Dict[str, Any]]) -> None:
        if not patches:
            return
        section = self._new_section("Generated Patches")
        tbl = ReportTable(
            title="Patches",
            headers=["Patch ID", "File", "Type", "Risk", "Score", "Applied"],
        )
        for p in patches[:50]:
            risk = p.get("risk_level", "low")
            tbl.add_row(
                str(p.get("patch_id", "—"))[:10],
                str(p.get("file_path", "—"))[-40:],
                p.get("patch_type",  "—"),
                risk,
                round(float(p.get("score", 0)), 4),
                "YES" if p.get("applied") else "no",
            )

        # severity summary
        high_risk = sum(1 for p in patches if p.get("risk_level", "").lower() in ("high", "critical"))
        blk = MetricBlock("Patch Risk Summary")
        blk.add("Total Patches", len(patches))
        blk.add("High/Critical Risk", high_risk,
                severity=ReportSeverity.CRITICAL if high_risk > 0 else ReportSeverity.INFO)
        section.add_metric_block(blk)
        section.add_table(tbl)

    def _build_mutations_section(self, mutations: Dict[str, Any]) -> None:
        if not mutations:
            return
        section = self._new_section("Mutation A/B Tests")
        blk = MetricBlock("Mutation Stats")
        blk.add("Active Tests",     mutations.get("active",    0))
        blk.add("Concluded Tests",  mutations.get("concluded", 0))
        blk.add("Variants Total",   mutations.get("variants",  0))
        section.add_metric_block(blk)

        tests: List[Dict[str, Any]] = mutations.get("tests", [])
        if tests:
            tbl = ReportTable(
                title="A/B Tests",
                headers=["Test ID", "Variant", "Metric", "Winner", "Confidence", "Status"],
            )
            for t in tests[:20]:
                tbl.add_row(
                    str(t.get("test_id",    "—"))[:10],
                    t.get("variant_name", "—"),
                    t.get("metric",       "—"),
                    t.get("winner",       "—"),
                    round(float(t.get("confidence", 0)), 4),
                    t.get("status",       "—"),
                )
            section.add_table(tbl)

    def _build_repairs_section(self, repairs: List[Dict[str, Any]]) -> None:
        if not repairs:
            return
        rollbacks = [r for r in repairs if r.get("action") == "rollback"]
        sev       = ReportSeverity.WARNING if rollbacks else ReportSeverity.INFO

        section = self._new_section("Self-Repair Events", severity=sev)
        tbl = ReportTable(
            title="Repair Events",
            headers=["File", "Action", "Reason", "OK", "Timestamp"],
        )
        for r in repairs[-30:]:
            tbl.add_row(
                str(r.get("file_path", "—"))[-40:],
                r.get("action",   "—"),
                str(r.get("reason", "—"))[:60],
                "YES" if r.get("ok") else "FAIL",
                r.get("timestamp", "—"),
            )
        section.add_table(tbl)
