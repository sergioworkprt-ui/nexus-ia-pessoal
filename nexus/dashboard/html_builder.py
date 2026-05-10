"""Minimal HTML builder utilities for the NEXUS server-side dashboard."""
from __future__ import annotations

STYLE = """
<style>
  :root{--bg:#0a0e1a;--panel:#111827;--border:#1f2937;
        --accent:#3b82f6;--ok:#10b981;--warn:#f59e0b;--err:#ef4444;--text:#e5e7eb;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;font-size:14px;}
  header{display:flex;align-items:center;gap:12px;padding:16px 24px;
         border-bottom:1px solid var(--border);}
  .logo{font-size:1.25rem;font-weight:700;letter-spacing:.2em;color:var(--accent);}
  .dot{width:10px;height:10px;border-radius:50%;background:var(--accent);
       animation:pulse 2s infinite;}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
  main{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px;}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:16px;}
  .card h2{font-size:.75rem;text-transform:uppercase;letter-spacing:.1em;
            color:var(--accent);margin-bottom:12px;}
  table{width:100%;border-collapse:collapse;font-size:.8rem;}
  th,td{padding:6px 8px;text-align:left;border-bottom:1px solid var(--border);}
  th{color:#9ca3af;font-weight:600;}
  .ok{color:var(--ok);} .warn{color:var(--warn);} .err{color:var(--err);}
  pre{font-family:monospace;font-size:.75rem;white-space:pre-wrap;
      max-height:300px;overflow-y:auto;color:#9ca3af;}
  .badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.7rem;}
  .badge-sim{background:#10b98122;color:var(--ok);}
  .badge-real{background:#ef444422;color:var(--err);}
  footer{text-align:center;padding:16px;font-size:.75rem;color:#4b5563;
         border-top:1px solid var(--border);}
</style>
"""


def page(title: str, body: str, refresh: int = 10) -> str:
    """Wrap body in a complete HTML page with auto-refresh."""
    return (
        "<!DOCTYPE html><html lang='pt'>"
        f"<head><meta charset='UTF-8'><title>{title}</title>"
        f"<meta http-equiv='refresh' content='{refresh}'>"
        f"{STYLE}</head><body>"
        "<header><div class='dot'></div>"
        "<span class='logo'>NEXUS</span></header>"
        f"<main>{body}</main>"
        "<footer>NEXUS Dashboard &mdash; actualiza a cada "
        f"{refresh}s</footer></body></html>"
    )


def status_card(status: dict) -> str:
    """Render the system status card."""
    if "error" in status:
        return (
            "<div class='card'><h2>Estado do Sistema</h2>"
            f"<p class='err'>{status['error']}</p></div>"
        )
    mode = status.get("trading_mode", "simulation")
    badge_cls = "badge-real" if mode == "real" else "badge-sim"
    modules = status.get("modules", {})
    rows = "".join(
        f"<tr><td>{k}</td><td class='{'ok' if v == 'running' else 'err'}'>{v}</td></tr>"
        for k, v in modules.items()
    )
    return (
        "<div class='card'><h2>Estado do Sistema</h2>"
        f"<p>Modo: <span class='badge {badge_cls}'>{mode.upper()}</span></p>"
        f"<br><table><tr><th>Módulo</th><th>Estado</th></tr>{rows}</table></div>"
    )


def positions_card(data: dict) -> str:
    """Render the open positions card."""
    positions = data.get("positions", [])
    if not positions:
        return (
            "<div class='card'><h2>Posições Abertas</h2>"
            "<p style='color:#6b7280'>Sem posições abertas.</p></div>"
        )
    rows = ""
    for p in positions:
        pnl = p.get("pnl", 0)
        pnl_cls = "ok" if pnl >= 0 else "err"
        pnl_str = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
        rows += (
            f"<tr><td>{p.get('symbol','')}</td>"
            f"<td>{p.get('side','')}</td>"
            f"<td>{p.get('size','')}</td>"
            f"<td>{p.get('entry_price','')}</td>"
            f"<td class='{pnl_cls}'>{pnl_str}€</td>"
            f"<td style='color:#9ca3af'>{p.get('broker','')}</td></tr>"
        )
    return (
        "<div class='card'><h2>Posições Abertas</h2>"
        "<table><tr><th>Symbol</th><th>Side</th><th>Size</th>"
        "<th>Entry</th><th>P&amp;L</th><th>Broker</th></tr>"
        f"{rows}</table></div>"
    )


def logs_card(lines: list[str], service: str) -> str:
    """Render a log viewer card."""
    content = "\n".join(lines[-50:]) if lines else "(sem logs)"
    return (
        f"<div class='card'><h2>Logs — {service}</h2>"
        f"<pre>{content}</pre></div>"
    )
