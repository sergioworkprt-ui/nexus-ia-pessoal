"""
Dashboard HTML Builder
Produces HTML strings using Python f-strings — no template engine needed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Theme constants (dark NEXUS palette)
# ---------------------------------------------------------------------------

_NAV_LINKS: List[Tuple[str, str]] = [
    ("/",               "Overview"),
    ("/pipelines",      "Pipelines"),
    ("/signals",        "Signals"),
    ("/risk",           "Risk"),
    ("/evolution",      "Evolution"),
    ("/audit",          "Audit"),
    ("/reports",        "Reports"),
    ("/limits",         "Limits"),
    ("/ibkr",           "IBKR"),
]

_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 14px;
    background: #0d1117;
    color: #e6edf3;
    min-height: 100vh;
}
a { color: #58a6ff; text-decoration: none; }
a:hover { text-decoration: underline; }

/* Nav */
nav {
    background: #161b22;
    border-bottom: 1px solid #30363d;
    display: flex;
    align-items: center;
    padding: 0 24px;
    height: 52px;
    gap: 8px;
}
.nav-brand {
    font-weight: 700;
    font-size: 16px;
    color: #58a6ff;
    margin-right: 24px;
    letter-spacing: 0.05em;
}
.nav-link {
    color: #8b949e;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 13px;
    transition: background .15s, color .15s;
}
.nav-link:hover { background: #21262d; color: #e6edf3; text-decoration: none; }
.nav-link.active { background: #21262d; color: #e6edf3; font-weight: 600; }

/* Layout */
.container { max-width: 1200px; margin: 0 auto; padding: 24px 24px 48px; }
h1 { font-size: 22px; margin-bottom: 4px; }
.subtitle { color: #8b949e; font-size: 13px; margin-bottom: 24px; }

/* Grid */
.grid { display: grid; gap: 16px; }
.grid-2 { grid-template-columns: repeat(2, 1fr); }
.grid-3 { grid-template-columns: repeat(3, 1fr); }
.grid-4 { grid-template-columns: repeat(4, 1fr); }
@media (max-width: 900px) { .grid-4, .grid-3 { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .grid-4, .grid-3, .grid-2 { grid-template-columns: 1fr; } }

/* Cards */
.card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 20px;
}
.card-title {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #8b949e;
    margin-bottom: 12px;
}
.stat-value { font-size: 28px; font-weight: 700; line-height: 1.2; }
.stat-sub { font-size: 12px; color: #8b949e; margin-top: 4px; }
.section-title {
    font-size: 16px;
    font-weight: 600;
    margin: 28px 0 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid #30363d;
}

/* Table */
.table-wrap { overflow-x: auto; }
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}
th {
    text-align: left;
    padding: 8px 12px;
    background: #161b22;
    border-bottom: 1px solid #30363d;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #8b949e;
    font-weight: 600;
    white-space: nowrap;
}
td {
    padding: 8px 12px;
    border-bottom: 1px solid #21262d;
    vertical-align: middle;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: #1c2128; }
.table-empty {
    text-align: center;
    padding: 32px;
    color: #8b949e;
    font-style: italic;
}

/* Badges */
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
}
.badge-success  { background: #1a3a1a; color: #3fb950; border: 1px solid #3fb950; }
.badge-warning  { background: #3a2a0a; color: #d29922; border: 1px solid #d29922; }
.badge-error    { background: #3a0a0a; color: #f85149; border: 1px solid #f85149; }
.badge-info     { background: #0a1f3a; color: #58a6ff; border: 1px solid #58a6ff; }
.badge-muted    { background: #21262d; color: #8b949e; border: 1px solid #30363d; }
.badge-purple   { background: #2a0a3a; color: #bc8cff; border: 1px solid #bc8cff; }

/* Module dots */
.dot {
    display: inline-block; width: 8px; height: 8px;
    border-radius: 50%; margin-right: 6px;
}
.dot-green  { background: #3fb950; box-shadow: 0 0 4px #3fb950; }
.dot-red    { background: #f85149; box-shadow: 0 0 4px #f85149; }
.dot-yellow { background: #d29922; box-shadow: 0 0 4px #d29922; }

/* Audit entry */
.audit-ts { color: #8b949e; font-family: monospace; font-size: 12px; white-space: nowrap; }
.audit-event { font-family: monospace; font-size: 12px; }
.mono { font-family: 'Courier New', monospace; font-size: 12px; }

/* Alert banner */
.alert {
    padding: 12px 16px;
    border-radius: 6px;
    margin-bottom: 16px;
    font-size: 13px;
}
.alert-warning { background: #3a2a0a; border: 1px solid #d29922; color: #d29922; }
.alert-error   { background: #3a0a0a; border: 1px solid #f85149; color: #f85149; }
.alert-info    { background: #0a1f3a; border: 1px solid #58a6ff; color: #58a6ff; }

/* Key-value pairs */
.kv-row { display: flex; padding: 6px 0; border-bottom: 1px solid #21262d; gap: 16px; }
.kv-row:last-child { border-bottom: none; }
.kv-key { color: #8b949e; min-width: 200px; font-size: 13px; }
.kv-val { font-size: 13px; }
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _badge(text: str, style: str = "muted") -> str:
    return f'<span class="badge badge-{style}">{_esc(str(text))}</span>'


def _dot(ready: bool) -> str:
    cls = "dot-green" if ready else "dot-red"
    return f'<span class="dot {cls}"></span>'


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _mode_badge(mode: str) -> str:
    style = {"enabled": "success", "dry_run": "warning", "disabled": "error"}.get(mode, "muted")
    return _badge(mode, style)


def _status_badge(status: str) -> str:
    style = {"success": "success", "partial": "warning", "failed": "error",
             "skipped": "muted", "running": "info"}.get(status.lower(), "muted")
    return _badge(status, style)


def _fmt_interval(secs: int) -> str:
    if not secs:
        return "—"
    h, rem = divmod(int(secs), 3600)
    m = rem // 60
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    if m:
        return f"{m}m"
    return f"{secs}s"


def _fmt_ts(ts: str) -> str:
    if not ts:
        return "—"
    return ts[:19].replace("T", " ")


# ---------------------------------------------------------------------------
# Page scaffold
# ---------------------------------------------------------------------------

def page(title: str, body: str, active: str = "/") -> str:
    nav_html = "".join(
        f'<a href="{href}" class="nav-link{" active" if href == active else ""}">{label}</a>'
        for href, label in _NAV_LINKS
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>NEXUS — {_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<nav>
  <span class="nav-brand">⬡ NEXUS</span>
  {nav_html}
</nav>
<div class="container">
{body}
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Reusable components
# ---------------------------------------------------------------------------

def stat_card(label: str, value: Any, sub: str = "", color: str = "") -> str:
    style = f' style="color:{color}"' if color else ""
    return f"""<div class="card">
  <div class="card-title">{_esc(label)}</div>
  <div class="stat-value"{style}>{_esc(str(value))}</div>
  {f'<div class="stat-sub">{_esc(sub)}</div>' if sub else ''}
</div>"""


def kv_table(pairs: List[Tuple[str, str]]) -> str:
    rows = "".join(
        f'<div class="kv-row"><span class="kv-key">{_esc(k)}</span>'
        f'<span class="kv-val">{v}</span></div>'
        for k, v in pairs
    )
    return f'<div class="card">{rows}</div>'


def data_table(headers: List[str], rows: List[List[str]], empty: str = "No data available.") -> str:
    if not rows:
        return f'<div class="card"><div class="table-empty">{_esc(empty)}</div></div>'
    th_html = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    tr_html = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"""<div class="card table-wrap">
<table><thead><tr>{th_html}</tr></thead><tbody>{tr_html}</tbody></table>
</div>"""
