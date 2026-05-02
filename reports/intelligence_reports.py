"""
NEXUS Reports — Intelligence Reports
Structured reports from web_intelligence data:
market patterns, anomalies, sentiment trends, and news summaries.
Works with live WebIntelligence data or plain dicts (offline).
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

def _sentiment_severity(score: float) -> ReportSeverity:
    if abs(score) > 0.6:
        return ReportSeverity.CRITICAL
    if abs(score) > 0.3:
        return ReportSeverity.WARNING
    return ReportSeverity.INFO


def _pattern_severity(pattern_type: str) -> ReportSeverity:
    critical_patterns = {"anomaly_price", "anomaly_volume", "breakdown", "bearish_divergence"}
    warning_patterns  = {"breakout", "double_top", "double_bottom", "high_volatility",
                         "resistance_test", "support_test", "bullish_divergence"}
    pt = pattern_type.lower()
    if pt in critical_patterns:
        return ReportSeverity.CRITICAL
    if pt in warning_patterns:
        return ReportSeverity.WARNING
    return ReportSeverity.INFO


# ---------------------------------------------------------------------------
# IntelligenceReport
# ---------------------------------------------------------------------------

class IntelligenceReport(BaseReport):
    """
    Market intelligence report combining pattern detection,
    sentiment analysis, and news summaries.
    """

    report_type = "intelligence"

    def __init__(self, title: str = "Market Intelligence Report") -> None:
        super().__init__(
            title=title,
            description="Patterns, anomalies, sentiment, and news summaries.",
        )

    # ------------------------------------------------------------------
    # Primary factories
    # ------------------------------------------------------------------

    @classmethod
    def from_intelligence(
        cls,
        web_intelligence: Any,
        symbol:           str = "MARKET",
    ) -> "IntelligenceReport":
        """Build report from a live WebIntelligence facade."""
        report = cls(title=f"Intelligence Report — {symbol}")
        try:
            status = web_intelligence.status()
        except Exception as exc:
            report._meta["engine_error"] = str(exc)
            report._new_section("Error", body=str(exc), severity=ReportSeverity.CRITICAL)
            return report.finalise()

        patterns  = status.get("pattern_detector", {})
        sentiment = status.get("news_analyzer",    {})
        fetcher   = status.get("fetcher",          {})

        report._build_fetcher_section(fetcher)
        report._build_patterns_section(patterns)
        report._build_sentiment_section(sentiment)
        return report.finalise()

    @classmethod
    def from_dict(
        cls,
        data:         Dict[str, Any],
        period_label: str = "snapshot",
    ) -> "IntelligenceReport":
        report = cls(title=f"Intelligence Report — {period_label}")
        report._build_fetcher_section(data.get("fetcher", {}))
        report._build_patterns_section(data.get("patterns", {}))
        report._build_sentiment_section(data.get("sentiment", {}))
        report._build_news_table(data.get("news", []))
        return report.finalise()

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_fetcher_section(self, fetcher: Dict[str, Any]) -> None:
        if not fetcher:
            return
        section = self._new_section("Web Fetcher Stats")
        blk = MetricBlock("Fetch Activity")
        blk.add("Total Fetches",     fetcher.get("total_fetches",    0))
        blk.add("Successful",        fetcher.get("successful",       0))
        blk.add("Failed",            fetcher.get("failed",           0))
        blk.add("Avg Latency (ms)",  round(float(fetcher.get("avg_latency_ms", 0)), 2), "ms")
        section.add_metric_block(blk)

    def _build_patterns_section(self, patterns: Dict[str, Any]) -> None:
        detected: List[Dict[str, Any]] = patterns.get("detected_patterns", [])
        if not detected and isinstance(patterns, list):
            detected = patterns  # allow raw list

        total    = len(detected)
        critical = sum(1 for p in detected
                       if _pattern_severity(p.get("type", "")) == ReportSeverity.CRITICAL)

        sev = ReportSeverity.CRITICAL if critical > 0 else (
              ReportSeverity.WARNING  if total > 0    else ReportSeverity.INFO)

        section = self._new_section("Detected Patterns", severity=sev)

        blk = MetricBlock("Pattern Summary")
        blk.add("Total Detected", total)
        blk.add("Critical",       critical, severity=ReportSeverity.CRITICAL if critical else ReportSeverity.INFO)
        blk.add("Non-critical",   total - critical)
        section.add_metric_block(blk)

        if detected:
            tbl = ReportTable(
                title="Pattern Detail",
                headers=["Type", "Symbol", "Confidence", "Detected At", "Notes"],
            )
            for p in detected[:50]:  # cap at 50 rows
                tbl.add_row(
                    p.get("type",         "—"),
                    p.get("symbol",       "—"),
                    round(float(p.get("confidence", 0)), 4),
                    p.get("detected_at",  "—"),
                    p.get("notes",        ""),
                )
            section.add_table(tbl)

    def _build_sentiment_section(self, sentiment: Dict[str, Any]) -> None:
        if not sentiment:
            return

        score = float(sentiment.get("average_score", sentiment.get("score", 0.0)))
        sev   = _sentiment_severity(score)

        section = self._new_section("Sentiment Overview", severity=sev)

        blk = MetricBlock("Sentiment Metrics")
        blk.add("Average Score",     round(score, 4), "",
                severity=sev,
                note="Range: -1.0 (bearish) to +1.0 (bullish)")
        blk.add("Articles Analysed", sentiment.get("articles_analysed", 0))
        blk.add("Bullish Signals",   sentiment.get("bullish_count",      0))
        blk.add("Bearish Signals",   sentiment.get("bearish_count",      0))
        blk.add("Risk Keywords Hit", sentiment.get("risk_hits",          0),
                severity=ReportSeverity.WARNING if int(sentiment.get("risk_hits", 0)) > 0 else ReportSeverity.INFO)
        section.add_metric_block(blk)

        # Per-source breakdown
        sources: Dict[str, Any] = sentiment.get("by_source", {})
        if sources:
            tbl = ReportTable(
                title="Sentiment by Source",
                headers=["Source", "Score", "Articles", "Credibility"],
            )
            for src, info in sources.items():
                if isinstance(info, dict):
                    tbl.add_row(
                        src,
                        round(float(info.get("score",       0)), 4),
                        info.get("articles",    0),
                        round(float(info.get("credibility", 0)), 2),
                    )
            section.add_table(tbl)

    def _build_news_table(self, news: List[Dict[str, Any]]) -> None:
        if not news:
            return
        section = self._new_section("News Summary")
        tbl = ReportTable(
            title="Recent News Items",
            headers=["Headline", "Source", "Sentiment", "Risk", "Published"],
        )
        for item in news[:30]:
            tbl.add_row(
                str(item.get("headline", item.get("title", "—")))[:80],
                item.get("source",    "—"),
                round(float(item.get("sentiment_score", 0)), 4),
                "YES" if item.get("has_risk_keywords") else "no",
                item.get("published_at", item.get("date", "—")),
            )
        section.add_table(tbl)

    # ------------------------------------------------------------------
    # Standalone helpers
    # ------------------------------------------------------------------

    def add_anomaly_alert(
        self,
        symbol:      str,
        anomaly_type: str,
        detail:      str,
        confidence:  float = 1.0,
    ) -> None:
        """Add a specific anomaly alert section."""
        sev = _pattern_severity(anomaly_type)
        section = self._new_section(
            f"Anomaly Alert — {symbol}",
            body=detail,
            severity=sev,
        )
        blk = MetricBlock("Anomaly Details")
        blk.add("Symbol",     symbol)
        blk.add("Type",       anomaly_type, severity=sev)
        blk.add("Confidence", round(confidence, 4))
        blk.add("Detected At", datetime.now(timezone.utc).isoformat())
        section.add_metric_block(blk)
