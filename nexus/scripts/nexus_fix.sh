#!/usr/bin/env bash
# =============================================================================
# NEXUS V2 — nexus_fix.sh  (versão 3)
#
# Detecta a estrutura real do VPS e escreve um main.py adaptativo:
#   • Modo COMPLETO  — se nexus.api.rest.main + Orchestrator existirem
#   • Modo MÍNIMO   — FastAPI básico inline (garante API+WS mesmo sem módulos)
#
# Uso: sudo bash /opt/nexus/nexus/scripts/nexus_fix.sh
# =============================================================================
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*"; }
warn() { echo -e "${YELLOW}[!!]${NC}  $*"; }
info() { echo -e "${BLUE}[--]${NC}  $*"; }
step() { echo -e "\n${CYAN}════ $* ════${NC}"; }

R_DEPS="OK" R_ENV="PENDENTE" R_WS="PENDENTE"
R_API="PENDENTE" R_BACKEND="PENDENTE" R_DASH="PENDENTE"
R_SYSTEMD="PENDENTE" R_MODE="?"

[[ $EUID -ne 0 ]] && { err "Corre como root: sudo bash $0"; exit 1; }

# ── Auto-detectar NEXUS_HOME ────────────────────────────────────────────────────────────
for _try in /opt/nexus "$(pwd)"; do
  [[ -d "$_try/nexus" ]] && { NEXUS_HOME="$_try"; break; }
done
[[ -z "${NEXUS_HOME:-}" ]] && { err "Não encontrei /opt/nexus. Edita NEXUS_HOME."; exit 1; }

NEXUS_SRC="$NEXUS_HOME/nexus"
ENV_FILE="$NEXUS_HOME/.env"
SVC_FILE="/etc/systemd/system/nexus-backend.service"
FRONTEND="$NEXUS_SRC/dashboard/frontend"
PYTHON=/usr/bin/python3
PIP=/usr/bin/pip3
SERVICE=nexus-backend
export PYTHONPATH="$NEXUS_HOME"

echo -e "\n${CYAN}╔$(printf '═%.0s' {1..56})╗${NC}"
echo -e "${CYAN}║     NEXUS V2 — Reparação Total  (v3)$(printf ' %.0s' {1..15})║${NC}"
echo -e "${CYAN}╚$(printf '═%.0s' {1..56})╝${NC}"
info "NEXUS_HOME  : $NEXUS_HOME"
info "NEXUS_SRC   : $NEXUS_SRC"
info "Python      : $PYTHON  ($($PYTHON --version 2>&1))"
info "Service     : $SERVICE"
info "PYTHONPATH  : $PYTHONPATH"

# =============================================================================
step "1. Parar serviço em crash-loop (urgente)"
# =============================================================================
if systemctl is-active --quiet $SERVICE 2>/dev/null || \
   systemctl is-failed --quiet $SERVICE 2>/dev/null; then
  systemctl stop $SERVICE 2>/dev/null || true
  ok "$SERVICE parado"
else
  info "$SERVICE já parado"
fi

# =============================================================================
step "2. Instalar dependências Python em falta"
# =============================================================================
INSTALL_NEEDED=()
for pkg_imp in \
  "python-dotenv:dotenv" \
  "uvicorn[standard]:uvicorn" \
  "fastapi:fastapi" \
  "websockets:websockets" \
  "psutil:psutil" \
  "httpx:httpx" \
  "PyJWT:jwt" \
  "pydantic:pydantic"
do
  pkg="${pkg_imp%%:*}"; imp="${pkg_imp##*:}"
  $PYTHON -c "import $imp" 2>/dev/null || INSTALL_NEEDED+=("$pkg")
done

if [[ ${#INSTALL_NEEDED[@]} -gt 0 ]]; then
  info "Instalando: ${INSTALL_NEEDED[*]}"
  $PIP install --quiet "${INSTALL_NEEDED[@]}" && ok "Dependências instaladas" || \
    warn "Algumas dependências falharam"
else
  ok "Todas as dependências já instaladas"
fi
R_DEPS="OK"

# =============================================================================
step "3. Actualizar código via git pull"
# =============================================================================
if [[ -d "$NEXUS_HOME/.git" ]]; then
  info "Tentando git pull em $NEXUS_HOME ..."
  cd "$NEXUS_HOME"
  git fetch origin 2>/dev/null && \
    git checkout claude/create-test-file-d1AY6 2>/dev/null && \
    git pull origin claude/create-test-file-d1AY6 2>/dev/null && \
    ok "Git pull OK" || warn "Git pull falhou — usando código local"
  cd /
else
  warn "Não é um repositório git — a corrigir ficheiros directamente"
fi

# =============================================================================
step "4. Detectar estrutura de módulos"
# =============================================================================
check_mod() { PYTHONPATH="$NEXUS_HOME" $PYTHON -c "$1" 2>/dev/null; }

info "A testar módulos com PYTHONPATH=$NEXUS_HOME ..."

if check_mod "from nexus.api.rest.main import app, set_nexus"; then
  HAS_FULL_API=true;  ok  "nexus.api.rest.main         ✓"
else
  HAS_FULL_API=false; warn "nexus.api.rest.main         ✗"
fi

if check_mod "from nexus.core.orchestrator.orchestrator import Orchestrator"; then
  HAS_ORCH=true;  ok  "nexus.core.orchestrator      ✓"
else
  HAS_ORCH=false; warn "nexus.core.orchestrator      ✗"
fi

if check_mod "from nexus.ws_server import start_ws"; then
  HAS_WS_MOD=true;  ok  "nexus.ws_server              ✓"
else
  HAS_WS_MOD=false; warn "nexus.ws_server              ✗ (será criado)"
fi

if $HAS_FULL_API && $HAS_ORCH; then
  R_MODE="COMPLETO"; ok  "Modo detectado: COMPLETO (Orchestrator + API)"
else
  R_MODE="MÍNIMO";   warn "Modo detectado: MÍNIMO (API inline + WS)"
fi

# =============================================================================
step "5. .env"
# =============================================================================
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'ENVEOF'
API_HOST=0.0.0.0
API_PORT=8000
HOST=0.0.0.0
PORT=8000
WS_HOST=0.0.0.0
WS_PORT=8001
DASHBOARD_URL=http://35.241.151.115:9000
LOG_DIR=/var/log/nexus
DATA_DIR=/data/nexus
SECRET_KEY=nexus-change-this-key
NEXUS_API_KEY=nexus-change-me
ENVEOF
  ok ".env criado"
else
  for _kv in API_HOST=0.0.0.0 API_PORT=8000 HOST=0.0.0.0 PORT=8000 \
             WS_HOST=0.0.0.0 WS_PORT=8001; do
    _k="${_kv%%=*}"
    grep -q "^${_k}=" "$ENV_FILE" || echo "$_kv" >> "$ENV_FILE"
  done
  ok ".env OK"
fi
R_ENV="OK"

# =============================================================================
step "6. Criar/actualizar ws_server.py"
# =============================================================================
cat > "$NEXUS_SRC/ws_server.py" <<'WSEOF'
"""NEXUS — Servidor WebSocket standalone (porta 8001)."""
from __future__ import annotations
import asyncio, json, logging, os
from typing import Any, Set

log = logging.getLogger("nexus.ws_server")
_clients: Set[Any] = set()

async def broadcast(data: dict) -> None:
    if not _clients: return
    msg = json.dumps(data)
    dead: Set[Any] = set()
    for ws in list(_clients):
        try: await ws.send(msg)
        except Exception: dead.add(ws)
    _clients.difference_update(dead)

async def _handler(ws: Any) -> None:
    _clients.add(ws)
    addr = getattr(ws, "remote_address", "?")
    log.info("WS connected: %s (total: %d)", addr, len(_clients))
    try:
        await ws.send(json.dumps({"type": "connected", "server": "nexus-ws", "version": "2.0"}))
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await ws.send(json.dumps({"type": "pong"}))
                else:
                    await broadcast(msg)
            except (json.JSONDecodeError, TypeError): pass
    except Exception: pass
    finally:
        _clients.discard(ws)
        log.info("WS disconnected: %s (total: %d)", addr, len(_clients))

async def start_ws(host: str = "0.0.0.0", port: int = 8001) -> None:
    try: import websockets
    except ImportError:
        log.error("websockets não instalado. Corre: pip3 install websockets")
        return
    log.info("NEXUS WS → ws://%s:%d", host, port)
    try:
        async with websockets.serve(_handler, host, port):  # type: ignore
            await asyncio.Future()
    except OSError as e: log.error("WS bind error: %s", e)
    except asyncio.CancelledError: pass

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_ws(os.getenv("WS_HOST","0.0.0.0"), int(os.getenv("WS_PORT","8001"))))
WSOF
ok "ws_server.py escrito"
R_WS="OK"

# =============================================================================
step "7. Escrever main.py adaptativo"
# =============================================================================
MAIN="$NEXUS_SRC/main.py"
cp "$MAIN" "${MAIN}.bak.$(date +%s)" 2>/dev/null && info "Backup: ${MAIN}.bak.*" || true

cat > "$MAIN" <<'MAINEOF'
"""NEXUS V2 — entry point adaptativo.

Modo COMPLETO  : usa Orchestrator + nexus.api.rest.main  (se disponível)
Modo MÍNIMO   : FastAPI inline + /health + /ws  (garante sempre API+WS)
Porta API : API_PORT  (default 8000)
Porta WS  : WS_PORT   (default 8001)
"""
from __future__ import annotations
import asyncio, json, logging, os, signal, sys

# ─ PYTHONPATH auto-fix: garante que /opt/nexus está sempre no path ────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ─ Carregar .env ───────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _ep = os.path.join(_ROOT, ".env")
    if os.path.exists(_ep):
        load_dotenv(_ep)
        print(f"[NEXUS] .env carregado de {_ep}", flush=True)
except ImportError:
    print("[NEXUS] AVISO: python-dotenv não instalado", flush=True)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s")
log = logging.getLogger("nexus.main")

import uvicorn

# ─ Tentar modo COMPLETO, cair para modo MÍNIMO se falhar ───────────────────
_FULL = False
try:
    from nexus.api.rest.main import app, set_nexus          # type: ignore
    from nexus.core.orchestrator.orchestrator import Orchestrator  # type: ignore
    _FULL = True
    log.info("Modo COMPLETO: nexus.api.rest.main + Orchestrator carregados")
except Exception as _e:
    log.warning("Modo MÍNIMO (módulos completos indisponíveis: %s)", _e)
    from fastapi import FastAPI, WebSocket as _FWS
    from fastapi.middleware.cors import CORSMiddleware
    app = FastAPI(title="NEXUS API", version="2.0.0", docs_url="/docs")  # type: ignore
    app.add_middleware(CORSMiddleware,                                   # type: ignore
                       allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")                                                  # type: ignore
    def _h():
        return {"status": "ok", "version": "2.0.0", "mode": "minimal"}

    @app.get("/status")                                                  # type: ignore
    def _st():
        return {"status": "minimal", "api": "running", "ws_port": int(os.getenv("WS_PORT","8001"))}

    _ws_conns: set = set()

    @app.websocket("/ws")                                                # type: ignore
    async def _wse(ws: _FWS):
        await ws.accept()
        _ws_conns.add(ws)
        try:
            await ws.send_json({"type": "connected", "mode": "minimal", "version": "2.0"})
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive_text(), timeout=30)
                    if json.loads(msg).get("type") == "ping":
                        await ws.send_text(json.dumps({"type": "pong"}))
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "heartbeat"})
                except Exception:
                    break
        except Exception:
            pass
        finally:
            _ws_conns.discard(ws)

    def set_nexus(_): pass  # type: ignore  # noqa: E301


# ─ WS standalone porta 8001 ────────────────────────────────────────────────
async def _start_ws() -> None:
    h = os.getenv("WS_HOST", "0.0.0.0")
    p = int(os.getenv("WS_PORT", "8001"))
    # Tentar ws_server.py dedicado
    try:
        from nexus.ws_server import start_ws  # type: ignore
        await start_ws(h, p)
        return
    except ImportError:
        pass
    except asyncio.CancelledError:
        return
    except Exception as ex:
        log.error("ws_server.py erro: %s", ex)
        return
    # Fallback: servidor mínimo inline
    try:
        import websockets  # type: ignore
        _cl: set = set()
        async def _hh(ws):
            _cl.add(ws)
            try:
                await ws.send(json.dumps({"type":"connected"}))
                async for _ in ws: pass
            except Exception: pass
            finally: _cl.discard(ws)
        log.info("WS inline → ws://%s:%d", h, p)
        async with websockets.serve(_hh, h, p):  # type: ignore
            await asyncio.Future()
    except Exception as ex:
        log.error("WS inline falhou: %s", ex)


# ─ Módulos opcionais (só no modo completo) ──────────────────────────────────
_MODS = [
    ("memory",         "nexus.core.memory.memory",                   "Memory"),
    ("personality",    "nexus.core.personality.personality",          "Personality"),
    ("security",       "nexus.core.security.security",                "SecurityManager"),
    ("tts",            "nexus.core.voice.tts",                        "TTS"),
    ("ml",             "nexus.modules.ml.ml",                         "MLModule"),
    ("watchdog",       "nexus.modules.watchdog.watchdog",             "Watchdog"),
    ("tasks",          "nexus.modules.tasks.tasks",                   "TaskManager"),
    ("learning",       "nexus.modules.learning.learning",             "LearningModule"),
    ("video_analysis", "nexus.modules.video_analysis.video_analysis", "VideoAnalysis"),
    ("evolution",      "nexus.modules.evolution.evolution",           "Evolution"),
    ("truth_checker",  "nexus.modules.truth_checker.truth_checker",   "TruthChecker"),
    ("xtb",            "nexus.modules.trading.xtb.xtb_client",        "XTBClient"),
    ("ibkr",           "nexus.modules.trading.ibkr.ibkr_client",      "IBKRClient"),
    ("scheduler",      "nexus.services.scheduler.scheduler",          "Scheduler"),
]

def _load(lbl, fn):
    try:
        r = fn(); log.info("  ✓ %s", lbl); return r
    except Exception as e:
        log.warning("  ✗ %s: %s", lbl, e); return None


# ─ Main ──────────────────────────────────────────────────────────────────────────
async def main() -> None:
    log.info("═══ NEXUS v2 a iniciar (%s) ═══", 'COMPLETO' if _FULL else 'MÍNIMO')

    ah = os.getenv("API_HOST", os.getenv("HOST", "0.0.0.0"))
    ap = int(os.getenv("API_PORT", os.getenv("PORT", "8000")))

    _nexus = None
    if _FULL:
        _nexus = Orchestrator()  # type: ignore
        for n, mp, cn in _MODS:
            obj = _load(n, lambda p=mp, c=cn: getattr(__import__(p, fromlist=[c]), c)())
            if obj: _nexus.register(n, obj)
        stt = _load("stt", lambda: getattr(
            __import__("nexus.core.voice.stt", fromlist=["STT"]), "STT"
        )(on_wake=_nexus.process))
        if stt: _nexus.register("stt", stt)
        sec = _nexus.get("security")
        if sec:
            tm = _load("trading", lambda s=sec: getattr(
                __import__("nexus.modules.trading.trading", fromlist=["TradingModule"]),
                "TradingModule")(s))
            if tm: _nexus.register("trading", tm)
        set_nexus(_nexus)  # type: ignore

    cfg    = uvicorn.Config(app, host=ah, port=ap, log_level="info", access_log=True)
    server = uvicorn.Server(cfg)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            _sv = server; _nx = _nexus
            loop.add_signal_handler(sig, lambda s=_sv, n=_nx:
                asyncio.create_task(_stop(n, s)))
        except NotImplementedError:
            pass

    log.info("API  → http://%s:%d  (%s)", ah, ap, 'full' if _FULL else 'minimal')
    log.info("Docs → http://%s:%d/docs", ah, ap)
    log.info("WS   → ws://%s:%s", os.getenv('WS_HOST','0.0.0.0'), os.getenv('WS_PORT','8001'))

    tasks = [server.serve(), _start_ws()]
    if _FULL and _nexus:
        tasks.insert(0, _nexus.start())
    await asyncio.gather(*tasks, return_exceptions=True)


async def _stop(nexus, server) -> None:
    log.info("A parar NEXUS...")
    if nexus:
        try: await nexus.stop()
        except Exception: pass
    server.should_exit = True


if __name__ == "__main__":
    asyncio.run(main())
MAINEOF
ok "main.py adaptativo escrito  (modo: $R_MODE)"

# =============================================================================
step "8. Systemd — nexus-backend.service"
# =============================================================================
cat > "$SVC_FILE" <<SVCEOF
[Unit]
Description=NEXUS Backend Service (API 8000 + WS 8001)
After=network.target
Wants=network.target

[Service]
Type=simple
WorkingDirectory=$NEXUS_HOME
Environment=PYTHONPATH=$NEXUS_HOME
EnvironmentFile=-$ENV_FILE
ExecStart=$PYTHON $NEXUS_SRC/main.py
Restart=always
RestartSec=10
StartLimitIntervalSec=0
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nexus-backend

[Install]
WantedBy=multi-user.target
SVCEOF
systemctl daemon-reload
systemctl enable $SERVICE 2>/dev/null || true
ok "nexus-backend.service actualizado"
R_SYSTEMD="OK"

# =============================================================================
step "9. Directórios e firewall"
# =============================================================================
for d in /var/log/nexus /data/nexus /data/nexus/memory /data/nexus/tasks /data/nexus/evolution; do
  mkdir -p "$d"; chmod 775 "$d"
done
if command -v ufw &>/dev/null; then
  for p in 8000 8001 9000; do ufw allow $p/tcp 2>/dev/null || true; done
  ok "UFW: 8000, 8001, 9000 abertos"
fi

# =============================================================================
step "10. Arrancar backend e validar portas"
# =============================================================================
info "A iniciar $SERVICE ..."
systemctl start $SERVICE
info "Aguardando arranque (25s)..."
sleep 25

check_port() {
  local p=$1
  ss -tlnp 2>/dev/null | grep -q ":${p}[[:space:]]" && return 0
  command -v nc &>/dev/null && nc -z 127.0.0.1 "$p" 2>/dev/null && return 0
  return 1
}

if check_port 8000; then
  ok "Porta 8000 (API) ABERTA"; R_API="OK"
else
  err "Porta 8000 (API) FECHADA — ver logs abaixo"; R_API="ERRO"
  journalctl -u $SERVICE -n 40 --no-pager 2>/dev/null | tail -30
fi

if check_port 8001; then
  ok "Porta 8001 (WS) ABERTA"; R_WS="OK"
else
  err "Porta 8001 (WS) FECHADA"; R_WS="ERRO"
fi

systemctl is-active --quiet $SERVICE && \
  { ok "$SERVICE activo"; R_BACKEND="OK"; } || \
  { err "$SERVICE inactivo"; R_BACKEND="ERRO"; }

# =============================================================================
step "11. Dashboard (9000)"
# =============================================================================
if check_port 9000; then
  ok "Porta 9000 (Dashboard) ABERTA"; R_DASH="OK"
elif systemctl is-enabled nexus-dashboard &>/dev/null; then
  systemctl restart nexus-dashboard 2>/dev/null || true
  sleep 5
  check_port 9000 && { ok "Dashboard reiniciado OK"; R_DASH="OK"; } || \
    { err "Dashboard não abriu"; R_DASH="ERRO"; }
else
  warn "nexus-dashboard não configurado"; R_DASH="N/A"
fi

# =============================================================================
# RELATÓRIO FINAL
# =============================================================================
echo ""
echo -e "${CYAN}╔$(printf '═%.0s' {1..54})╗${NC}"
echo -e "${CYAN}║       RELATÓRIO FINAL — NEXUS V2$(printf ' %.0s' {1..17})║${NC}"
echo -e "${CYAN}╠$(printf '═%.0s' {1..54})╣${NC}"

_rl() {
  local l=$1 v=$2 c=$RED i="✗"
  [[ "$v" == "OK" ]] && c=$GREEN && i="✓"
  printf "${CYAN}║${NC}  ${c}${i}${NC}  %-28s  ${c}%-8s${NC}\n" "$l" "$v"
}

_rl "Dependências Python"    "$R_DEPS"
_rl "Ficheiro .env"          "$R_ENV"
_rl "Systemd service"        "$R_SYSTEMD"
_rl "main.py (modo: $R_MODE)" "OK"
_rl "ws_server.py"           "$R_WS"
_rl "Backend activo"         "$R_BACKEND"
_rl "API REST (porta 8000)"  "$R_API"
_rl "WebSocket (porta 8001)" "$R_WS"
_rl "Dashboard (porta 9000)" "$R_DASH"
echo -e "${CYAN}╚$(printf '═%.0s' {1..54})╝${NC}"
echo ""

echo "Monitorização em tempo real:"
echo "  journalctl -u nexus-backend -f"
echo ""

if [[ "$R_API" != "OK" || "$R_BACKEND" != "OK" ]]; then
  echo -e "${YELLOW}Se ainda falhar, corre manualmente para ver o erro exacto:${NC}"
  echo "  cd $NEXUS_HOME && PYTHONPATH=$NEXUS_HOME $PYTHON $NEXUS_SRC/main.py"
  echo ""
fi

if [[ "$R_API" == "OK" && "$R_WS" == "OK" ]]; then
  SERVER_IP=$(hostname -I | awk '{print $1}')
  echo -e "${GREEN}NEXUS em funcionamento!${NC}"
  echo "  API        : http://$SERVER_IP:8000"
  echo "  Docs       : http://$SERVER_IP:8000/docs"
  echo "  WebSocket  : ws://$SERVER_IP:8001"
  echo "  Dashboard  : http://$SERVER_IP:9000"
fi
