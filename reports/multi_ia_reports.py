"""
NEXUS Reports — Multi-IA Reports
Structured reports from the multi_ia subsystem:
consensus results, agent performance, contradictions, pipeline history,
disagreements, and escalation events.
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

def _agreement_severity(score: float) -> ReportSeverity:
    if score < 0.30:
        return ReportSeverity.CRITICAL
    if score < 0.60:
        return ReportSeverity.WARNING
    return ReportSeverity.INFO


def _contradiction_severity(severity_str: str) -> ReportSeverity:
    mapping = {
        "low":      ReportSeverity.INFO,
        "medium":   ReportSeverity.WARNING,
        "high":     ReportSeverity.CRITICAL,
        "critical": ReportSeverity.CRITICAL,
    }
    return mapping.get(severity_str.lower(), ReportSeverity.INFO)


# ---------------------------------------------------------------------------
# MultiIAReport
# ---------------------------------------------------------------------------

class MultiIAReport(BaseReport):
    """
    Report covering multi-agent consensus, performance, and disagreements.
    """

    report_type = "multi_ia"

    def __init__(self, title: str = "Multi-IA Report") -> None:
        super().__init__(
            title=title,
            description="Consensus results, agent performance, contradictions.",
        )

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @classmethod
    def from_multi_ia(
        cls,
        multi_ia:    Any,
        history_limit: int = 20,
    ) -> "MultiIAReport":
        """Build from a live MultiIA facade."""
        report = cls()
        try:
            status  = multi_ia.status()
            history = multi_ia.history(limit=history_limit)
        except Exception as exc:
            report._meta["engine_error"] = str(exc)
            report._new_section("Error", body=str(exc), severity=ReportSeverity.CRITICAL)
            return report.finalise()

        report._build_system_section(status)
        report._build_agent_section(status.get("agents", []))
        report._build_consensus_section(status.get("consensus", {}))
        report._build_pipeline_history(history)
        return report.finalise()

    @classmethod
    def from_dict(
        cls,
        data:         Dict[str, Any],
        period_label: str = "snapshot",
    ) -> "MultiIAReport":
        report = cls(title=f"Multi-IA Report — {period_label}")
        report._build_system_section(data)
        report._build_agent_section(data.get("agents", []))
        report._build_consensus_section(data.get("consensus", {}))
        report._build_pipeline_history(data.get("history", []))
        report._build_contradictions_table(data.get("contradictions", []))
        return report.finalise()

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_system_section(self, status: Dict[str, Any]) -> None:
        section = self._new_section("System Overview")

        reg   = status.get("registry",     {})
        orch  = status.get("orchestrator", {})

        blk = MetricBlock("Subsystem Stats")
        blk.add("Running",          "YES" if status.get("running") else "NO")
        blk.add("Total Agents",     reg.get("total",     0))
        blk.add("Available Agents", reg.get("available", 0),
                severity=ReportSeverity.WARNING if int(reg.get("available", 1)) == 0 else ReportSeverity.INFO)
        blk.add("Disabled Agents",  reg.get("disabled",  0))
        blk.add("Total Pipelines",  orch.get("total_pipelines",  0))
        blk.add("Successful",       orch.get("successful",        0))
        blk.add("Failed",           orch.get("failed",            0),
                severity=ReportSeverity.WARNING if int(orch.get("failed", 0)) > 0 else ReportSeverity.INFO)
        blk.add("Avg Pipeline (ms)", round(float(orch.get("avg_total_ms", 0)), 2), "ms")
        section.add_metric_block(blk)

    def _build_agent_section(self, agents: List[Dict[str, Any]]) -> None:
        if not agents:
            return
        section = self._new_section("Agent Performance")
        tbl = ReportTable(
            title="Agent Stats",
            headers=["Name", "Provider", "Status", "Calls", "Errors", "Avg Latency (ms)", "Confidence"],
        )
        for a in agents:
            error_rate = a.get("error_rate", 0)
            tbl.add_row(
                a.get("name",         "—"),
                a.get("provider",     "—"),
                a.get("status",       "—"),
                a.get("call_count",   0),
                a.get("error_count",  0),
                round(float(a.get("avg_latency_ms", 0)), 2),
                round(float(a.get("avg_confidence", 0)), 4),
            )

        blk = MetricBlock("Fleet Summary")
        total_calls  = sum(int(a.get("call_count",  0)) for a in agents)
        total_errors = sum(int(a.get("error_count", 0)) for a in agents)
        error_pct    = (total_errors / total_calls * 100) if total_calls else 0.0
        blk.add("Total Calls",  total_calls)
        blk.add("Total Errors", total_errors,
                severity=ReportSeverity.WARNING if total_errors > 0 else ReportSeverity.INFO)
        blk.add("Error Rate",   round(error_pct, 2), "%",
                severity=ReportSeverity.CRITICAL if error_pct > 10 else
                         ReportSeverity.WARNING  if error_pct > 3  else ReportSeverity.INFO)
        section.add_metric_block(blk)
        section.add_table(tbl)

    def _build_consensus_section(self, consensus: Dict[str, Any]) -> None:
        if not consensus:
            return

        avg_agree  = float(consensus.get("avg_agreement_score", 0.0))
        escalations = int(consensus.get("escalations", 0))
        sev = max(
            _agreement_severity(avg_agree),
            ReportSeverity.CRITICAL if escalations > 0 else ReportSeverity.INFO,
            key=lambda s: ["info", "warning", "critical"].index(s.value),
        )

        section = self._new_section("Consensus Analytics", severity=sev)
        blk = MetricBlock("Consensus Stats")
        blk.add("Total Consensus Runs", consensus.get("total_consensus_runs", 0))
        blk.add("Avg Agreement Score",  round(avg_agree, 4),
                severity=_agreement_severity(avg_agree),
                note="1.0 = full agreement")
        blk.add("Escalations",          escalations,
                severity=ReportSeverity.CRITICAL if escalations > 0 else ReportSeverity.INFO)
        section.add_metric_block(blk)

    def _build_pipeline_history(self, history: List[Dict[str, Any]]) -> None:
        if not history:
            return
        section = self._new_section("Pipeline History")
        tbl = ReportTable(
            title="Recent Pipelines",
            headers=["ID", "Name", "Strategy", "Steps", "OK", "Total (ms)", "Finished At"],
        )
        for h in history[-20:]:
            tbl.add_row(
                str(h.get("pipeline_id", "—"))[:10],
                h.get("name",       "—"),
                h.get("strategy",   "—"),
                h.get("steps",       0),
                "YES" if h.get("ok") else "FAIL",
                round(float(h.get("total_ms", 0)), 2),
                str(h.get("finished_at", "—"))[:19],
            )
        section.add_table(tbl)

    def _build_contradictions_table(self, contradictions: List[Dict[str, Any]]) -> None:
        if not contradictions:
            return
        high = [c for c in contradictions
                if c.get("severity", "").lower() in ("high", "critical")]
        sev  = ReportSeverity.CRITICAL if high else ReportSeverity.WARNING

        section = self._new_section("Contradiction Log", severity=sev)
        blk = MetricBlock("Contradiction Summary")
        blk.add("Total",    len(contradictions))
        blk.add("High/Critical", len(high),
                severity=ReportSeverity.CRITICAL if high else ReportSeverity.INFO)
        section.add_metric_block(blk)

        tbl = ReportTable(
            title="Contradictions",
            headers=["ID", "Agent A", "Agent B", "Type", "Severity", "Description"],
        )
        for c in contradictions[:30]:
            tbl.add_row(
                str(c.get("contradiction_id", "—"))[:10],
                c.get("agent_a",     "—"),
                c.get("agent_b",     "—"),
                c.get("type",        "—"),
                c.get("severity",    "—"),
                str(c.get("description", ""))[:80],
            )
        section.add_table(tbl)

    # ------------------------------------------------------------------
    # Standalone helper
    # ------------------------------------------------------------------

    def add_consensus_result(
        self,
        result:    Any,
        task_label: str = "",
    ) -> None:
        """Append a single ConsensusResult (or dict) as a section."""
        d = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        agree = float(d.get("agreement_score", 0.0))
        sev   = _agreement_severity(agree)
        section = self._new_section(
            f"Consensus — {task_label or d.get('consensus_id', '?')}",
            severity=sev,
        )
        blk = MetricBlock("Result")
        blk.add("Method",          d.get("method",          "—"))
        blk.add("Selected Agent",  d.get("selected_agent",  "—"))
        blk.add("Agreement Score", round(agree, 4), severity=sev)
        blk.add("Confidence",      round(float(d.get("confidence", 0)), 4))
        blk.add("Responses Used",  d.get("responses_used",  0))
        blk.add("Contradictions",  d.get("contradictions",  0))
        blk.add("Escalated",       "YES" if d.get("escalated") else "no",
                severity=ReportSeverity.CRITICAL if d.get("escalated") else ReportSeverity.INFO)
        section.add_metric_block(blk)

        preview = str(d.get("final_content", ""))[:200]
        if preview:
            section.body = f"Preview: {preview}"
