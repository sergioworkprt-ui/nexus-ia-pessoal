"""
Dashboard Pages
One function per route — returns an HTML string.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from . import reader as R
from .html_builder import (
    _badge, _dot, _esc, _fmt_interval, _fmt_ts, _mode_badge, _status_badge,
    data_table, kv_table, page, stat_card,
)


# ---------------------------------------------------------------------------
# / — Overview
# ---------------------------------------------------------------------------

def render_overview() -> str:
    data       = R.read_overview()
    startup    = data["startup"]
    checkpoint = data["checkpoint"]
    modules    = data["modules"]
    audit      = data["audit_chain"]
    pipelines  = data["pipelines"]

    mode    = startup.get("mode", "unknown").upper()
    started = _fmt_ts(startup.get("started_at", ""))
    pid     = startup.get("_pid")
    running = startup.get("_pid_running", False)

    cycle_count = checkpoint.get("cycle_count", "—")
    uptime_s    = checkpoint.get("uptime_seconds", 0)
    uptime_str  = _fmt_interval(int(uptime_s)) if uptime_s else "—"
    last_cycle  = _fmt_ts(checkpoint.get("last_cycle_at", ""))

    # Mode colour
    mode_col = {"LIVE": "#3fb950", "SIMULATION": "#d29922", "DRY_RUN": "#d29922"}.get(mode, "#8b949e")

    # Stats row
    audit_ok = audit.get("available", False)
    stats_html = f"""<div class="grid grid-4">
  {stat_card("Mode", mode, f"started {started}", mode_col)}
  {stat_card("Cycles", cycle_count, f"uptime {uptime_str}")}
  {stat_card("Signals", data["signal_count"], "in signals_latest.json")}
  {stat_card("Audit Chain", "VALID ✓" if audit_ok else "N/A", f"{audit.get('entry_count', 0)} entries" if audit_ok else "not found", "#3fb950" if audit_ok else "#8b949e")}
</div>"""

    # Process status
    proc_badge = _badge(f"PID {pid} running", "success") if running else (
        _badge(f"PID {pid} stale", "warning") if pid else _badge("not running", "error")
    )

    # Modules
    mod_rows = []
    for name, ready in sorted(modules.items()):
        mod_rows.append([
            f"{_dot(ready)}{_esc(name)}",
            _badge("ready", "success") if ready else _badge("not ready", "error"),
        ])

    # Pipeline summary
    pipe_rows = []
    for name, info in pipelines.items():
        mode_b   = _mode_badge(info["mode"])
        last_run = _fmt_ts(info["last_run"]) if info["last_run"] != "never" else "never"
        errs     = info["error_count"]
        err_b    = _badge(str(errs), "error") if errs else _badge("0", "muted")
        pipe_rows.append([_esc(name), mode_b, _fmt_interval(info["interval_seconds"]),
                          _esc(last_run), _esc(str(info["run_count"])), err_b])

    body = f"""
<h1>NEXUS Overview</h1>
<p class="subtitle">System health and operational snapshot — auto-refreshes every 30 seconds.</p>
{stats_html}
<div class="section-title">Process</div>
<div class="card">
  <div class="kv-row">
    <span class="kv-key">Status</span><span class="kv-val">{proc_badge}</span>
  </div>
  <div class="kv-row">
    <span class="kv-key">Last cycle</span><span class="kv-val">{_esc(last_cycle or "—")}</span>
  </div>
  <div class="kv-row">
    <span class="kv-key">Version</span><span class="kv-val">{_esc(str(startup.get("version", "—")))}</span>
  </div>
</div>

<div class="section-title">Modules</div>
{data_table(["Module", "Status"], mod_rows, "No module data.")}

<div class="section-title">Pipelines</div>
{data_table(["Pipeline", "Mode", "Interval", "Last Run", "Runs", "Errors"],
             pipe_rows, "No pipeline data.")}
"""
    return page("Overview", body, active="/")


# ---------------------------------------------------------------------------
# /pipelines
# ---------------------------------------------------------------------------

def render_pipelines() -> str:
    pipelines = R.read_pipeline_status()
    cfg       = R.read_limits()
    sched     = cfg.get("pipelines", {}).get("pipelines", {})
    notes     = cfg.get("pipelines", {}).get("schedule_notes", {})
    events    = cfg.get("pipelines", {}).get("event_triggers", {})

    cards = []
    for name, info in pipelines.items():
        sched_info = sched.get(name, {})
        deps = info.get("dependencies", [])
        deps_str = ", ".join(deps) if deps else "none"
        dep_b = "".join(
            f' {_badge(d, "info")}' for d in deps
        )

        rows = [
            ("Mode",         _mode_badge(info["mode"])),
            ("Interval",     _esc(_fmt_interval(info["interval_seconds"]))),
            ("Last Run",     _esc(_fmt_ts(info["last_run"]) if info["last_run"] != "never" else "never")),
            ("Run Count",    _esc(str(info["run_count"]))),
            ("Error Count",  _badge(str(info["error_count"]), "error") if info["error_count"] else _badge("0", "success")),
            ("Dependencies", dep_b or _badge("none", "muted")),
            ("Timeout",      _esc(f"{sched_info.get('timeout_seconds', '—')}s")),
            ("Retries",      _esc(str(sched_info.get("max_retries", "—")))),
            ("Description",  _esc(info.get("description", ""))),
            ("Note",         _esc(notes.get(name, ""))),
        ]
        inner = "".join(
            f'<div class="kv-row"><span class="kv-key">{k}</span><span class="kv-val">{v}</span></div>'
            for k, v in rows if v and v != _esc("") and v != _esc("—")
        )
        cards.append(f'<div class="card"><div class="card-title">{_esc(name)}</div>{inner}</div>')

    cards_html = '<div class="grid grid-2">' + "".join(cards) + '</div>'

    # Event triggers table
    trig_rows = [
        [f'<code>{_esc(evt)}</code>', " ".join(_badge(p, "info") for p in pipes)]
        for evt, pipes in events.items()
    ]

    body = f"""
<h1>Pipelines</h1>
<p class="subtitle">Configuration and execution status of each NEXUS pipeline.</p>
{cards_html}
<div class="section-title">Event Triggers</div>
{data_table(["Event", "Triggers Pipeline(s)"], trig_rows, "No event triggers configured.")}
"""
    return page("Pipelines", body, active="/pipelines")


# ---------------------------------------------------------------------------
# /signals
# ---------------------------------------------------------------------------

def render_signals() -> str:
    signals = R.read_signals()

    rows = []
    for s in signals:
        symbol     = s.get("symbol", "—")
        score      = s.get("score", s.get("composite_score", "—"))
        action     = s.get("action", s.get("signal", "—"))
        confidence = s.get("confidence", "—")
        urgency    = s.get("urgency", "—")
        ts         = _fmt_ts(s.get("generated_at", s.get("ts", "")))

        # Score colour
        try:
            sc = float(score)
            score_col = "#3fb950" if sc >= 0.6 else ("#d29922" if sc >= 0.3 else "#f85149")
            score_str = f'<span style="color:{score_col};font-weight:600">{sc:.3f}</span>'
        except Exception:
            score_str = _esc(str(score))

        action_b = _badge(str(action), "success" if "buy" in str(action).lower() or
                          "long" in str(action).lower() else (
                          "error" if "sell" in str(action).lower() or
                          "exit" in str(action).lower() else "info"))

        urgency_b = {
            "immediate": _badge("immediate", "error"),
            "high":      _badge("high", "warning"),
            "medium":    _badge("medium", "info"),
            "low":       _badge("low", "muted"),
        }.get(str(urgency).lower(), _badge(str(urgency), "muted"))

        try:
            conf_pct = f"{float(confidence)*100:.0f}%"
        except Exception:
            conf_pct = str(confidence)

        rows.append([
            f'<strong>{_esc(symbol)}</strong>',
            score_str,
            action_b,
            _esc(conf_pct),
            urgency_b,
            _esc(ts),
        ])

    # Top-level stats
    total = len(signals)
    buy_count  = sum(1 for s in signals if "buy" in str(s.get("action", s.get("signal",""))).lower()
                     or "long" in str(s.get("action","")).lower())
    sell_count = sum(1 for s in signals if "sell" in str(s.get("action", s.get("signal",""))).lower()
                     or "exit" in str(s.get("action","")).lower())

    stats_html = f"""<div class="grid grid-3">
  {stat_card("Total Signals", total, "in signals_latest.json")}
  {stat_card("Buy / Long", buy_count, "", "#3fb950")}
  {stat_card("Sell / Exit", sell_count, "", "#f85149")}
</div>"""

    body = f"""
<h1>Signals</h1>
<p class="subtitle">Latest trade signals from the Signal Engine pipeline.</p>
{stats_html}
<div class="section-title">Signal Feed</div>
{data_table(["Symbol", "Score", "Action", "Confidence", "Urgency", "Generated"],
             rows, "No signals found. Run the reporting pipeline to generate signals_latest.json.")}
"""
    return page("Signals", body, active="/signals")


# ---------------------------------------------------------------------------
# /risk
# ---------------------------------------------------------------------------

def render_risk() -> str:
    checkpoint = R.read_checkpoint()
    cfg        = R.read_limits()
    runtime_cfg = cfg.get("runtime", {})

    financial_cfg  = runtime_cfg.get("financial", {})
    max_drawdown   = financial_cfg.get("max_drawdown_alert", "—")
    sharpe_alert   = financial_cfg.get("sharpe_alert", "—")
    backtest       = financial_cfg.get("backtest_on_start", False)

    pe_data = checkpoint.get("profit_engine_status", {})
    risk    = pe_data.get("risk", {})
    drawdown = risk.get("current_drawdown", "—")
    sharpe   = risk.get("sharpe_ratio", "—")

    try:
        dd_val = float(drawdown)
        dd_pct = f"{dd_val*100:.2f}%"
        dd_col = "#f85149" if dd_val >= float(max_drawdown) else (
                 "#d29922" if dd_val >= float(max_drawdown)*0.7 else "#3fb950")
    except Exception:
        dd_pct = str(drawdown)
        dd_col = "#8b949e"

    try:
        sh_val = float(sharpe)
        sh_str = f"{sh_val:.3f}"
        sh_col = "#3fb950" if sh_val >= 1.0 else ("#d29922" if sh_val >= 0 else "#f85149")
    except Exception:
        sh_str = str(sharpe)
        sh_col = "#8b949e"

    # Signal risk data
    signals = R.read_signals()
    risk_rows = []
    for s in signals:
        rm = s.get("risk", {})
        if not rm:
            continue
        sym    = s.get("symbol", "—")
        vol    = rm.get("volatility", "—")
        pos    = rm.get("position_size", "—")
        stop   = rm.get("stop_loss_pct", "—")
        tp     = rm.get("take_profit_pct", "—")
        score  = rm.get("risk_score", "—")
        try:
            sc = float(score)
            sc_col = "#f85149" if sc >= 0.7 else ("#d29922" if sc >= 0.4 else "#3fb950")
            sc_str = f'<span style="color:{sc_col};font-weight:600">{sc:.3f}</span>'
        except Exception:
            sc_str = _esc(str(score))
        try: vol_str = f"{float(vol)*100:.2f}%"
        except Exception: vol_str = str(vol)
        try: pos_str = f"{float(pos)*100:.2f}%"
        except Exception: pos_str = str(pos)
        try: stop_str = f"{float(stop)*100:.2f}%"
        except Exception: stop_str = str(stop)
        try: tp_str = f"{float(tp)*100:.2f}%"
        except Exception: tp_str = str(tp)

        risk_rows.append([
            f'<strong>{_esc(sym)}</strong>',
            _esc(vol_str), _esc(pos_str), _esc(stop_str), _esc(tp_str), sc_str,
        ])

    stats_html = f"""<div class="grid grid-3">
  {stat_card("Drawdown", dd_pct, f"alert @ {max_drawdown}", dd_col)}
  {stat_card("Sharpe Ratio", sh_str, f"alert below {sharpe_alert}", sh_col)}
  {stat_card("Backtest on Start", "yes" if backtest else "no", "")}
</div>"""

    alert_html = ""
    try:
        if float(drawdown) >= float(max_drawdown):
            alert_html = f'<div class="alert alert-error">⚠ Drawdown {dd_pct} has breached the alert threshold ({max_drawdown}).</div>'
    except Exception:
        pass

    body = f"""
<h1>Risk</h1>
<p class="subtitle">Portfolio risk metrics and signal-level risk evaluations.</p>
{alert_html}
{stats_html}
<div class="section-title">Limits (from live_runtime.json)</div>
{kv_table([
    ("max_drawdown_alert", _esc(str(max_drawdown))),
    ("sharpe_alert",       _esc(str(sharpe_alert))),
    ("backtest_on_start",  _esc(str(backtest))),
])}
<div class="section-title">Signal Risk Details</div>
{data_table(["Symbol", "Volatility", "Position Size", "Stop Loss", "Take Profit", "Risk Score"],
             risk_rows, "No risk data. Run the signal engine via the intelligence or financial pipeline.")}
"""
    return page("Risk", body, active="/risk")


# ---------------------------------------------------------------------------
# /audit
# ---------------------------------------------------------------------------

def render_audit() -> str:
    entries = R.read_audit_log(limit=50)
    chain   = R.read_audit_chain_status()

    chain_badge = _badge(f"VALID — {chain.get('entry_count', 0)} entries", "success") if chain.get("available") else _badge("not available", "muted")

    rows = []
    for e in entries:
        ts    = _fmt_ts(e.get("ts", ""))
        event = e.get("event", "")
        data  = e.get("data", {})
        data_str = ""
        if data and isinstance(data, dict):
            items = [(k, v) for k, v in list(data.items())[:3] if k not in ("ts", "event")]
            data_str = "  ".join(f"{k}={str(v)[:40]}" for k, v in items)

        rows.append([
            f'<span class="audit-ts">{_esc(ts)}</span>',
            f'<span class="audit-event">{_esc(str(event)[:80])}</span>',
            f'<span class="mono" style="color:#8b949e">{_esc(data_str[:100])}</span>',
        ])

    body = f"""
<h1>Audit Log</h1>
<p class="subtitle">Last 50 entries from <code>logs/live/audit_live.jsonl</code> — newest first.</p>
<div class="card" style="margin-bottom:16px">
  <div class="kv-row">
    <span class="kv-key">Audit chain</span><span class="kv-val">{chain_badge}</span>
  </div>
  <div class="kv-row">
    <span class="kv-key">Chain path</span>
    <span class="kv-val"><code>{_esc(chain.get("path","logs/audit_chain.jsonl"))}</code></span>
  </div>
</div>
{data_table(["Timestamp", "Event", "Detail"], rows, "No audit entries found.")}
"""
    return page("Audit", body, active="/audit")


# ---------------------------------------------------------------------------
# /reports
# ---------------------------------------------------------------------------

def render_reports() -> str:
    reports = R.read_reports_list()

    rows = []
    for r in reports:
        name     = r["name"]
        size     = r["size_kb"]
        modified = r["modified"]

        # Badge for report type
        rtype = "muted"
        for t in ("financial", "intelligence", "evolution", "multi_ia", "signal", "report"):
            if t in name.lower():
                rtype = {"financial": "success", "intelligence": "info",
                         "evolution": "purple", "multi_ia": "warning",
                         "signal": "info", "report": "muted"}.get(t, "muted")
                break

        rows.append([
            _badge(name.split("_")[0] if "_" in name else "report", rtype),
            f'<a href="/reports/{_esc(name)}">{_esc(name)}</a>',
            _esc(f"{size} KB"),
            _esc(modified),
        ])

    body = f"""
<h1>Reports</h1>
<p class="subtitle">JSON reports exported to <code>reports/live/</code>.</p>
{data_table(["Type", "File", "Size", "Modified"], rows, "No reports found. Run: python nexus_cli.py report")}
"""
    return page("Reports", body, active="/reports")


def render_report_detail(name: str) -> str:
    data = R.read_report_file(name)
    if data is None:
        body = f'<h1>Report Not Found</h1><p class="subtitle"><code>{_esc(name)}</code> does not exist in reports/live/.</p>'
        return page("Report Not Found", body, active="/reports")

    pretty = json.dumps(data, indent=2, default=str)
    body = f"""
<h1>{_esc(name)}</h1>
<p class="subtitle"><a href="/reports">← Back to Reports</a></p>
<div class="card">
  <pre class="mono" style="overflow-x:auto;white-space:pre-wrap;line-height:1.5">{_esc(pretty)}</pre>
</div>
"""
    return page(name, body, active="/reports")


# ---------------------------------------------------------------------------
# /limits
# ---------------------------------------------------------------------------

def render_limits() -> str:
    cfg     = R.read_limits()
    runtime = cfg.get("runtime", {})

    sections = []
    for section in ("intelligence", "financial", "evolution", "consensus", "reporting", "scheduler", "state"):
        data = runtime.get(section, {})
        if not data:
            continue
        rows = [(k, _esc(str(v))) for k, v in data.items() if not isinstance(v, (dict, list))]
        inner = "".join(
            f'<div class="kv-row"><span class="kv-key">{_esc(k)}</span>'
            f'<span class="kv-val">{v}</span></div>'
            for k, v in rows
        )
        sections.append(f'<div class="card"><div class="card-title">{_esc(section)}</div>{inner}</div>')

    grid = '<div class="grid grid-2">' + "".join(sections) + '</div>'

    # Top-level scalars
    top_pairs = [(k, _esc(str(v))) for k, v in runtime.items()
                 if not isinstance(v, (dict, list)) and not k.startswith("_")]

    body = f"""
<h1>Limits &amp; Config</h1>
<p class="subtitle">Current runtime limits from <code>config/live_runtime.json</code>. Use the Command Layer (<code>nexus_cli.py</code>) to modify limits.</p>
{kv_table(top_pairs) if top_pairs else ""}
{grid}
"""
    return page("Limits", body, active="/limits")


# ---------------------------------------------------------------------------
# /evolution
# ---------------------------------------------------------------------------

def render_evolution() -> str:
    data     = R.read_evolution_data()
    summary  = data["summary"]
    log      = data["log"]
    pending  = data["pending_proposals"]
    active   = data["active_adjustments"]

    # Performance stats from summary
    sig_count = summary.get("signal_count", "—")
    hit_rate  = summary.get("hit_rate", None)
    avg_score = summary.get("avg_score", None)
    vol_reg   = summary.get("volatility_regime", "—")
    quality   = summary.get("data_quality", "—")
    eval_at   = _fmt_ts(summary.get("evaluated_at", ""))

    try:
        hr_pct  = f"{float(hit_rate)*100:.1f}%"
        hr_col  = "#3fb950" if float(hit_rate) >= 0.6 else (
                  "#d29922" if float(hit_rate) >= 0.4 else "#f85149")
    except Exception:
        hr_pct  = "—"
        hr_col  = "#8b949e"

    try:
        avg_s_str = f"{float(avg_score):.3f}"
    except Exception:
        avg_s_str = "—"

    vol_col = {"low": "#3fb950", "medium": "#d29922", "high": "#f85149"}.get(
        str(vol_reg).lower(), "#8b949e"
    )

    no_data_alert = ""
    if not summary:
        no_data_alert = (
            '<div class="alert alert-info">No evolution summary yet. '
            'Run the reporting pipeline or use <code>evolve</code> in the command layer.</div>'
        )

    stats_html = f"""<div class="grid grid-4">
  {stat_card("Signals Evaluated", sig_count, f"last evaluated {eval_at}")}
  {stat_card("Hit Rate", hr_pct, "score ≥ 0.6", hr_col)}
  {stat_card("Avg Score", avg_s_str, "")}
  {stat_card("Volatility Regime", vol_reg.upper() if vol_reg != "—" else "—",
             f"data quality: {quality}", vol_col)}
</div>"""

    # Learning notes
    learning = summary.get("learning", {})
    notes    = learning.get("notes", [])
    notes_html = ""
    if notes:
        items = "".join(f"<li>{_esc(n)}</li>" for n in notes)
        notes_html = f'<div class="card"><div class="card-title">Learning Notes</div><ul style="padding-left:20px;line-height:2">{items}</ul></div>'

    # Pending proposals table
    def _impact_badge(lvl: str) -> str:
        return _badge(lvl, "warning" if lvl == "medium" else "info")

    def _sign_str(pct: float) -> str:
        col = "#3fb950" if pct > 0 else "#f85149"
        sign = "+" if pct >= 0 else ""
        return f'<span style="color:{col};font-weight:600">{sign}{pct:.1f}%</span>'

    pending_rows = []
    for p in pending:
        pending_rows.append([
            _esc(p.get("proposal_id", "")[:8]),
            f'<code>{_esc(p.get("parameter", ""))}</code>',
            _esc(str(p.get("current_value", ""))),
            _esc(str(p.get("proposed_value", ""))),
            _sign_str(float(p.get("change_pct", 0))),
            _impact_badge(p.get("impact_level", "low")),
            _esc(p.get("rationale", "")[:80]),
        ])

    # Active adjustments (last applied)
    active_rows = []
    for p in active:
        active_rows.append([
            f'<code>{_esc(p.get("parameter", ""))}</code>',
            _esc(str(p.get("current_value", ""))),
            _esc(str(p.get("proposed_value", ""))),
            _sign_str(float(p.get("change_pct", 0))),
            _impact_badge(p.get("impact_level", "low")),
        ])

    # History table
    history_rows = []
    for e in log[:15]:
        ts     = _fmt_ts(e.get("ts", ""))
        action = e.get("action", "?")
        evo_id = str(e.get("evo_id", "?"))[:10]
        n_prop = len(e.get("proposals", []))
        action_b = (_badge("apply", "success") if action == "apply" else
                    _badge("rollback", "warning") if action == "rollback" else
                    _badge(action, "muted"))
        history_rows.append([
            _esc(ts), action_b, f'<code>{_esc(evo_id)}</code>', _esc(str(n_prop)),
        ])

    body = f"""
<h1>Evolution Engine</h1>
<p class="subtitle">Controlled, data-driven parameter evolution — read-only view. Use the command layer to run or apply.</p>
{no_data_alert}
{stats_html}
{notes_html}
<div class="section-title">Pending Proposals</div>
{data_table(["ID", "Parameter", "Current", "Proposed", "Change", "Impact", "Rationale"],
             pending_rows,
             "No pending proposals. Run 'evolve' in the command layer: python nexus_cli.py")}
<div class="section-title">Last Applied Adjustments</div>
{data_table(["Parameter", "Was", "Now", "Change", "Impact"],
             active_rows,
             "No adjustments applied yet.")}
<div class="section-title">Evolution History</div>
{data_table(["Timestamp", "Action", "Evo ID", "Proposals"],
             history_rows,
             "No evolution log entries. Evolution log is written to logs/evolution_live.jsonl")}
"""
    return page("Evolution", body, active="/evolution")


# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------

def render_404(path: str) -> str:
    body = f"""
<h1>404 — Not Found</h1>
<p class="subtitle">The path <code>{_esc(path)}</code> does not exist.</p>
<p><a href="/">← Back to Overview</a></p>
"""
    return page("Not Found", body, active="")
