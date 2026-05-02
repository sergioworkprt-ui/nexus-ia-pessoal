"""
NEXUS Reports — Financial Reports
Generates structured reports from profit_engine data:
PnL, drawdown, exposure, Sharpe ratio, trade history, risk metrics.
Works with live ProfitEngine data or plain dicts (offline).
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .report_builder import (
    BaseReport, MetricBlock, ReportSection, ReportSeverity,
    ReportTable, Metric,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _sharpe(returns: List[float], risk_free: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free for r in returns]
    mean   = statistics.mean(excess)
    std    = statistics.stdev(excess)
    return _safe_div(mean, std) * math.sqrt(252)


def _max_drawdown(equity_curve: List[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _severity_from_drawdown(dd: float) -> ReportSeverity:
    if dd > 0.20:
        return ReportSeverity.CRITICAL
    if dd > 0.10:
        return ReportSeverity.WARNING
    return ReportSeverity.INFO


def _severity_from_pnl(pnl: float) -> ReportSeverity:
    if pnl < -1000:
        return ReportSeverity.CRITICAL
    if pnl < 0:
        return ReportSeverity.WARNING
    return ReportSeverity.INFO


# ---------------------------------------------------------------------------
# FinancialReport
# ---------------------------------------------------------------------------

class FinancialReport(BaseReport):
    """
    Full financial performance report.

    Can be built from a ProfitEngine instance (via from_engine()) or from
    raw metric dicts passed directly to the constructor helpers.
    """

    report_type = "financial"

    def __init__(self, title: str = "Financial Performance Report") -> None:
        super().__init__(title=title, description="PnL, risk, and trade analytics.")

    # ------------------------------------------------------------------
    # Primary factory
    # ------------------------------------------------------------------

    @classmethod
    def from_engine(cls, engine: Any, period_label: str = "current") -> "FinancialReport":
        """Build a report from a live ProfitEngine facade."""
        report = cls(title=f"Financial Report — {period_label}")
        try:
            status = engine.status()
        except Exception as exc:
            report._meta["engine_error"] = str(exc)
            report._new_section("Error", body=f"Could not retrieve engine status: {exc}",
                                 severity=ReportSeverity.CRITICAL)
            return report.finalise()

        portfolio = status.get("portfolio", {})
        risk      = status.get("risk",      {})

        report._build_portfolio_section(portfolio)
        report._build_risk_section(risk)
        report._build_trade_table(portfolio.get("open_positions", {}))
        return report.finalise()

    @classmethod
    def from_dict(
        cls,
        data:         Dict[str, Any],
        period_label: str = "snapshot",
    ) -> "FinancialReport":
        """Build a report from a plain data dict (offline use / tests)."""
        report = cls(title=f"Financial Report — {period_label}")
        report._build_portfolio_section(data.get("portfolio", data))
        report._build_risk_section(data.get("risk", {}))
        report._build_trade_table(data.get("positions", {}))
        return report.finalise()

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_portfolio_section(self, portfolio: Dict[str, Any]) -> None:
        cash        = float(portfolio.get("cash",        0.0))
        equity      = float(portfolio.get("equity",      cash))
        unrealised  = float(portfolio.get("unrealised_pnl", 0.0))
        realised    = float(portfolio.get("realised_pnl",   0.0))
        total_pnl   = unrealised + realised
        equity_curve: List[float] = portfolio.get("equity_curve", [equity])

        dd     = _max_drawdown(equity_curve)
        sharpe = _sharpe(portfolio.get("daily_returns", []))

        sev = max(
            _severity_from_pnl(total_pnl),
            _severity_from_drawdown(dd),
            key=lambda s: ["info", "warning", "critical"].index(s.value),
        )

        section = self._new_section("Portfolio Overview", severity=sev)

        blk = MetricBlock("Core Metrics")
        blk.add("Cash",              round(cash,       2), "USD")
        blk.add("Equity",            round(equity,     2), "USD")
        blk.add("Unrealised PnL",    round(unrealised, 2), "USD",
                severity=_severity_from_pnl(unrealised))
        blk.add("Realised PnL",      round(realised,   2), "USD",
                severity=_severity_from_pnl(realised))
        blk.add("Total PnL",         round(total_pnl,  2), "USD",
                severity=_severity_from_pnl(total_pnl))
        blk.add("Max Drawdown",      f"{dd * 100:.2f}", "%",
                severity=_severity_from_drawdown(dd))
        blk.add("Sharpe Ratio",      round(sharpe, 4), "",
                severity=ReportSeverity.WARNING if sharpe < 1.0 else ReportSeverity.INFO)
        section.add_metric_block(blk)

        # Equity curve summary
        if len(equity_curve) >= 2:
            blk2 = MetricBlock("Equity Curve")
            blk2.add("Start", round(equity_curve[0],  2), "USD")
            blk2.add("End",   round(equity_curve[-1], 2), "USD")
            blk2.add("High",  round(max(equity_curve), 2), "USD")
            blk2.add("Low",   round(min(equity_curve), 2), "USD")
            blk2.add("Points", len(equity_curve))
            section.add_metric_block(blk2)

    def _build_risk_section(self, risk: Dict[str, Any]) -> None:
        if not risk:
            return
        section = self._new_section("Risk Metrics")
        blk = MetricBlock("Risk Manager")
        for key, val in risk.items():
            if isinstance(val, (int, float, str, bool)):
                sev = ReportSeverity.WARNING if key.startswith("daily") and isinstance(val, float) and val > 0.8 else ReportSeverity.INFO
                blk.add(key.replace("_", " ").title(), val, severity=sev)
        section.add_metric_block(blk)

    def _build_trade_table(self, positions: Any) -> None:
        if not positions:
            return

        section = self._new_section("Open Positions")
        tbl = ReportTable(
            title="Open Positions",
            headers=["Symbol", "Side", "Size", "Avg Entry", "Current", "Unrealised PnL"],
        )

        if isinstance(positions, dict):
            for symbol, pos in positions.items():
                if isinstance(pos, dict):
                    tbl.add_row(
                        symbol,
                        pos.get("side",         "—"),
                        pos.get("size",          0),
                        round(float(pos.get("avg_entry", 0)), 4),
                        round(float(pos.get("current_price", 0)), 4),
                        round(float(pos.get("unrealised_pnl", 0)), 2),
                    )
                else:
                    tbl.add_row(symbol, str(pos), "—", "—", "—", "—")
        section.add_table(tbl)

    # ------------------------------------------------------------------
    # Standalone helpers
    # ------------------------------------------------------------------

    def add_trade_summary(
        self,
        trades:         List[Dict[str, Any]],
        section_title:  str = "Trade History",
    ) -> None:
        """Append a trade history table from a list of trade dicts."""
        section = self._new_section(section_title)
        tbl = ReportTable(
            title="Trades",
            headers=["ID", "Symbol", "Side", "Entry", "Exit", "PnL", "Duration"],
        )
        for t in trades:
            tbl.add_row(
                t.get("trade_id",  "—")[:8],
                t.get("symbol",    "—"),
                t.get("side",      "—"),
                round(float(t.get("entry_price", 0)), 4),
                round(float(t.get("exit_price",  0)), 4),
                round(float(t.get("pnl",         0)), 2),
                t.get("duration_s", "—"),
            )

        total_pnl = sum(float(t.get("pnl", 0)) for t in trades)
        wins      = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)
        losses    = len(trades) - wins
        win_rate  = _safe_div(wins, len(trades)) * 100 if trades else 0

        blk = MetricBlock("Trade Summary")
        blk.add("Total Trades", len(trades))
        blk.add("Wins",         wins)
        blk.add("Losses",       losses)
        blk.add("Win Rate",     round(win_rate, 2), "%")
        blk.add("Total PnL",    round(total_pnl, 2), "USD",
                severity=_severity_from_pnl(total_pnl))
        section.add_metric_block(blk)
        section.add_table(tbl)
