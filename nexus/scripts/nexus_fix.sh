#!/usr/bin/env bash
# =============================================================================
# NEXUS V2 — Diagnóstico e Reparação TOTAL
# Uso:  sudo bash nexus_fix.sh
# =============================================================================
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*"; }
warn() { echo -e "${YELLOW}[!!]${NC}  $*"; }
info() { echo -e "${BLUE}[--]${NC}  $*"; }
step() { echo -e "\n${CYAN}════ $* ════${NC}"; }

# Resultados do relatório final
R_DEPS="PENDENTE" R_ENV="PENDENTE" R_WS="PENDENTE"
R_API="PENDENTE"  R_BACKEND="PENDENTE" R_DASH="PENDENTE" R_SYSTEMD="PENDENTE"

[[ $EUID -ne 0 ]] && { err "Corre como root: sudo bash nexus_fix.sh"; exit 1; }

# ── Auto-detectar NEXUS_HOME ────────────────────────────────────────────────────────────────
if   [[ -f /opt/nexus/nexus/main.py ]]; then NEXUS_HOME=/opt/nexus
elif [[ -f ./nexus/main.py          ]]; then NEXUS_HOME="$(pwd)"
else err "Não encontrei NEXUS em /opt/nexus nem aqui. Edita NEXUS_HOME manualmente."; exit 1
fi

NEXUS_SRC="$NEXUS_HOME/nexus"
ENV_FILE="$NEXUS_HOME/.env"
SERVICE_FILE="/etc/systemd/system/nexus-backend.service"
FRONTEND_DIR="$NEXUS_SRC/dashboard/frontend"
PYTHON=/usr/bin/python3
PIP=/usr/bin/pip3
SERVICE=nexus-backend

echo -e "\n${CYAN}╔$(printf '═%.0s' {1..56})╗${NC}"
echo -e "${CYAN}║          NEXUS V2 — Reparação Total$(printf ' %.0s' {1..18})║${NC}"
echo -e "${CYAN}╚$(printf '═%.0s' {1..56})╝${NC}"
info "NEXUS_HOME : $NEXUS_HOME"
info "NEXUS_SRC  : $NEXUS_SRC"
info "Python     : $PYTHON"
info "Service    : $SERVICE"

# =============================================================================
step "1. Dependências Python"
# =============================================================================
info "Actualizando pip..."
$PIP install --quiet --upgrade pip 2>/dev/null || true

install_dep() {
  local pkg=$1 imp=$2
  if $PYTHON -c "import $imp" 2>/dev/null; then
    info "  $pkg ✓ (já instalado)"
  else
    info "  instalando $pkg ..."
    $PIP install --quiet "$pkg" 2>/dev/null && ok "  $pkg instalado" || warn "  $pkg não crítico, continuando"
  fi
}

# Críticos primeiro (falha = abort)
$PIP install --quiet "python-dotenv" "uvicorn[standard]" "fastapi" "websockets" \
  && ok "Dependências críticas OK" \
  || { err "Falha a instalar dependências críticas"; exit 1; }

# Opcionais
install_dep "psutil"                  "psutil"
install_dep "httpx"                   "httpx"
install_dep "PyJWT"                   "jwt"
install_dep "pyyaml"                  "yaml"
install_dep "pydantic"                "pydantic"
install_dep "anthropic"               "anthropic"
install_dep "openai"                  "openai"
install_dep "yt-dlp"                  "yt_dlp"
install_dep "youtube-transcript-api" "youtube_transcript_api"
install_dep "gTTS"                    "gtts"
install_dep "SpeechRecognition"       "speech_recognition"
install_dep "aiofiles"                "aiofiles"
R_DEPS="OK"; ok "Dependências OK"

# =============================================================================
step "2. Ficheiro .env"
# =============================================================================
if [[ ! -f "$ENV_FILE" ]]; then
  info "Criando $ENV_FILE ..."
  cat > "$ENV_FILE" <<'ENVEOF'
# NEXUS V2 — Configuração
API_HOST=0.0.0.0
API_PORT=8000
HOST=0.0.0.0
PORT=8000
WS_HOST=0.0.0.0
WS_PORT=8001
DASHBOARD_URL=http://35.241.151.115:9000
LOG_DIR=/var/log/nexus
DATA_DIR=/data/nexus
SECRET_KEY=nexus-change-this-key-use-openssl-rand-hex-32
NEXUS_API_KEY=nexus-change-me
ENVEOF
  ok ".env criado"
else
  # Garantir que as variáveis essenciais existem
  grep -q '^API_HOST=' "$ENV_FILE" || echo 'API_HOST=0.0.0.0'  >> "$ENV_FILE"
  grep -q '^API_PORT=' "$ENV_FILE" || echo 'API_PORT=8000'     >> "$ENV_FILE"
  grep -q '^HOST='     "$ENV_FILE" || echo 'HOST=0.0.0.0'      >> "$ENV_FILE"
  grep -q '^PORT='     "$ENV_FILE" || echo 'PORT=8000'          >> "$ENV_FILE"
  grep -q '^WS_HOST='  "$ENV_FILE" || echo 'WS_HOST=0.0.0.0'   >> "$ENV_FILE"
  grep -q '^WS_PORT='  "$ENV_FILE" || echo 'WS_PORT=8001'      >> "$ENV_FILE"
  ok ".env OK (existente actualizado)"
fi
R_ENV="OK"

# =============================================================================
step "3. Directórios"
# =============================================================================
for d in /var/log/nexus /data/nexus /data/nexus/memory /data/nexus/tasks /data/nexus/evolution; do
  mkdir -p "$d"
done
chmod -R 775 /var/log/nexus /data/nexus
ok "Directórios OK"

# =============================================================================
step "4. Servidor WebSocket standalone — ws_server.py"
# =============================================================================
WS_FILE="$NEXUS_SRC/ws_server.py"
info "Escrevendo $WS_FILE ..."
cat > "$WS_FILE" <<'WSEOF'
"""NEXUS — Servidor WebSocket standalone (porta 8001).

Inicia um servidor WebSocket puro (não-FastAPI) que o dashboard
frontend usa para actualiações em tempo real (avatar_state, métricas, etc.).
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
from typing import Any, Set

log = logging.getLogger("nexus.ws_server")
_clients: Set[Any] = set()


async def broadcast(data: dict) -> None:
    """Envia data a todos os clientes WebSocket ligados."""
    if not _clients:
        return
    msg = json.dumps(data)
    dead: Set[Any] = set()
    for ws in list(_clients):
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


async def _handler(ws) -> None:
    _clients.add(ws)
    addr = getattr(ws, "remote_address", "?")
    log.info(f"WS client connected: {addr}  (total: {len(_clients)})")
    try:
        await ws.send(json.dumps({"type": "connected", "server": "nexus-ws", "version": "2.0"}))
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await ws.send(json.dumps({"type": "pong"}))
                else:
                    await broadcast({"type": "relay", "data": msg})
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass
    finally:
        _clients.discard(ws)
        log.info(f"WS client disconnected: {addr}  (total: {len(_clients)})")


async def start_ws(host: str = "0.0.0.0", port: int = 8001) -> None:
    """Inicia o servidor WebSocket. Corre indefinidamente."""
    try:
        import websockets  # type: ignore
    except ImportError:
        log.error("Package 'websockets' não instalado. Corre: pip3 install websockets")
        return

    log.info(f"NEXUS WebSocket → ws://{host}:{port}")
    try:
        async with websockets.serve(_handler, host, port):  # type: ignore[attr-defined]
            log.info(f"NEXUS WebSocket a escutar em ws://{host}:{port}")
            await asyncio.Future()  # corre até ser cancelado
    except OSError as exc:
        log.error(f"Não consigo ligar WS a {host}:{port} → {exc}")
    except asyncio.CancelledError:
        log.info("WS server parado")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s  %(message)s")
    _h = os.getenv("WS_HOST", "0.0.0.0")
    _p = int(os.getenv("WS_PORT", "8001"))
    asyncio.run(start_ws(_h, _p))
WSOF
ok "ws_server.py criado"
R_WS="ESCRITO"

# =============================================================================
step "5. main.py — correção total (PYTHONPATH + WS + import fallback)"
# =============================================================================
MAIN_FILE="$NEXUS_SRC/main.py"
# Backup
cp "$MAIN_FILE" "${MAIN_FILE}.bak.$(date +%s)" 2>/dev/null && info "Backup: ${MAIN_FILE}.bak.*" || true
cat > "$MAIN_FILE" <<'MAINEOF'
"""NEXUS V2 — entry point.

Inicia:
  • FastAPI REST API + endpoint /ws   →  API_PORT  (default 8000)
  • Servidor WebSocket standalone    →  WS_PORT   (default 8001)
  • Todos os módulos NEXUS com fallback gracioso por módulo
"""
from __future__ import annotations
import asyncio
import logging
import os
import signal
import sys

# ─ Garantir que /opt/nexus está sempre no sys.path ────────────────────────────────
_NEXUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _NEXUS_ROOT not in sys.path:
    sys.path.insert(0, _NEXUS_ROOT)

# ─ Carregar .env ────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(_NEXUS_ROOT, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
        print(f"[NEXUS] .env carregado de {_env_path}", flush=True)
    else:
        print(f"[NEXUS] AVISO: .env não encontrado em {_env_path}", flush=True)
except ImportError:
    print("[NEXUS] AVISO: python-dotenv não instalado", flush=True)

# ─ Logging base ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
)
try:
    from nexus.services.logger.logger import get_logger
    log = get_logger("main")
except Exception:
    log = logging.getLogger("nexus.main")


# ─ Helper: importação segura ─────────────────────────────────────────────────────────────
def _load(label: str, factory):
    """Importa e instancia um módulo; retorna None em caso de erro."""
    try:
        obj = factory()
        log.info(f"  ✓ {label}")
        return obj
    except Exception as exc:
        log.warning(f"  ✗ {label}: {exc}")
        return None


# ─ Arranque do servidor WebSocket (porta 8001) ──────────────────────────────────
async def _start_ws() -> None:
    ws_host = os.getenv("WS_HOST", "0.0.0.0")
    ws_port = int(os.getenv("WS_PORT", "8001"))
    try:
        from nexus.ws_server import start_ws
        await start_ws(ws_host, ws_port)
    except ImportError:
        log.warning("ws_server.py não encontrado — WS na porta 8001 desactivado")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        log.error(f"WS server erro: {exc}")


# ─ Módulos opcionais ──────────────────────────────────────────────────────────────────
_MODULE_MAP = [
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


# ─ Main ───────────────────────────────────────────────────────────────────────────────
async def main() -> None:
    log.info("═══ NEXUS v2 a iniciar ═══")

    # Imports críticos — se falharem, não continuamos
    try:
        import uvicorn
        from nexus.api.rest.main import app, set_nexus
        from nexus.core.orchestrator.orchestrator import Orchestrator
    except ImportError as exc:
        log.critical(f"Import crítico falhou: {exc}")
        log.critical("Dica: define PYTHONPATH=/opt/nexus no serviço systemd")
        sys.exit(1)

    nexus = Orchestrator()

    # Carregar módulos opcionais (cada um independente)
    for name, mod_path, cls_name in _MODULE_MAP:
        obj = _load(
            name,
            lambda p=mod_path, c=cls_name:
                getattr(__import__(p, fromlist=[c]), c)()
        )
        if obj:
            nexus.register(name, obj)

    # STT precisa de nexus.process como callback
    stt = _load("stt", lambda: getattr(
        __import__("nexus.core.voice.stt", fromlist=["STT"]), "STT"
    )(on_wake=nexus.process))
    if stt:
        nexus.register("stt", stt)

    # TradingModule precisa do SecurityManager
    sec = nexus.get("security")
    if sec:
        tm = _load("trading", lambda s=sec: getattr(
            __import__("nexus.modules.trading.trading", fromlist=["TradingModule"]),
            "TradingModule"
        )(s))
        if tm:
            nexus.register("trading", tm)

    set_nexus(nexus)

    # Configuração da API
    api_host = os.getenv("API_HOST", os.getenv("HOST", "0.0.0.0"))
    api_port = int(os.getenv("API_PORT", os.getenv("PORT", "8000")))

    cfg    = uvicorn.Config(app, host=api_host, port=api_port,
                            log_level="info", access_log=True)
    server = uvicorn.Server(cfg)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                sig, lambda: asyncio.create_task(_stop(nexus, server))
            )
        except NotImplementedError:
            pass

    log.info(f"API  → http://{api_host}:{api_port}")
    log.info(f"Docs → http://{api_host}:{api_port}/docs")
    log.info(f"WS   → ws://{os.getenv('WS_HOST', '0.0.0.0')}:{os.getenv('WS_PORT', '8001')}")

    await asyncio.gather(
        nexus.start(),
        server.serve(),
        _start_ws(),
        return_exceptions=True,
    )


async def _stop(nexus, server) -> None:
    log.info("A parar NEXUS...")
    await nexus.stop()
    server.should_exit = True


if __name__ == "__main__":
    asyncio.run(main())
MAINEOF
ok "main.py reescrito (PYTHONPATH auto-fix + WS + import fallback)"

# =============================================================================
step "6. Systemd — nexus-backend.service"
# =============================================================================
info "Reescrevendo $SERVICE_FILE ..."
cat > "$SERVICE_FILE" <<SVCEOF
[Unit]
Description=NEXUS Backend Service (API porta 8000 + WS porta 8001)
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
ok "nexus-backend.service actualizado (PYTHONPATH=$NEXUS_HOME)"
R_SYSTEMD="OK"

# =============================================================================
step "7. Firewall — portas 8000, 8001, 9000"
# =============================================================================
if command -v ufw &>/dev/null; then
  ufw allow 8000/tcp comment 'NEXUS API'       2>/dev/null || true
  ufw allow 8001/tcp comment 'NEXUS WS'        2>/dev/null || true
  ufw allow 9000/tcp comment 'NEXUS Dashboard' 2>/dev/null || true
  ok "UFW: portas 8000, 8001, 9000 abertas"
elif command -v iptables &>/dev/null; then
  for p in 8000 8001 9000; do
    iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || \
    iptables -I INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || true
  done
  ok "iptables: portas 8000, 8001, 9000 abertas"
else
  warn "Firewall não detectado — verifica manualmente as portas"
fi

# =============================================================================
step "8. Reiniciar backend e validar portas"
# =============================================================================
info "A parar servico..."
systemctl stop $SERVICE 2>/dev/null || true
sleep 2
info "A iniciar servico..."
systemctl start $SERVICE
info "Aguardando arranque (20s)..."
sleep 20

check_port() {
  local p=$1
  # Tenta ss, netstat, ou nc
  ss -tlnp 2>/dev/null | grep -q ":${p}[[:space:]]" && return 0
  netstat -tlnp 2>/dev/null | grep -q ":${p}[[:space:]]" && return 0
  command -v nc &>/dev/null && nc -z 127.0.0.1 "$p" 2>/dev/null && return 0
  return 1
}

if check_port 8000; then
  ok "Porta 8000 (API) ABERTA"; R_API="OK"
else
  err "Porta 8000 (API) FECHADA"; R_API="ERRO"
  warn "Últimos logs:"
  journalctl -u $SERVICE -n 30 --no-pager 2>/dev/null || true
fi

if check_port 8001; then
  ok "Porta 8001 (WS) ABERTA"; R_WS="OK"
else
  err "Porta 8001 (WS) FECHADA"; R_WS="ERRO"
fi

if systemctl is-active --quiet $SERVICE; then
  ok "Serviço $SERVICE activo"; R_BACKEND="OK"
else
  err "Serviço $SERVICE não está activo"; R_BACKEND="ERRO"
fi

# =============================================================================
step "9. Frontend — rebuild e dashboard"
# =============================================================================
if [[ -d "$FRONTEND_DIR" ]]; then
  if [[ ! -d "$FRONTEND_DIR/dist" ]] || [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    info "A construir frontend..."
    cd "$FRONTEND_DIR"
    npm ci --silent 2>/dev/null && npm run build --silent 2>/dev/null && \
      ok "Frontend construído" || warn "Build frontend falhou"
    cd "$NEXUS_HOME"
  else
    ok "Frontend já construído (dist/ existe)"
  fi
  # Reiniciar nexus-dashboard se existir
  if systemctl is-enabled nexus-dashboard &>/dev/null; then
    systemctl restart nexus-dashboard 2>/dev/null && ok "nexus-dashboard reiniciado" || true
  fi
  if check_port 9000; then
    ok "Porta 9000 (Dashboard) ABERTA"; R_DASH="OK"
  else
    warn "Porta 9000 (Dashboard) fechada — servico nexus-dashboard não activo"
    R_DASH="SEM SERVIÇO"
  fi
else
  warn "Frontend não encontrado em $FRONTEND_DIR"
  R_DASH="N/A"
fi

# =============================================================================
# RELATÓRIO FINAL
# =============================================================================
echo ""
echo -e "${CYAN}╔$(printf '═%.0s' {1..50})╗${NC}"
echo -e "${CYAN}║            RELATÓRIO FINAL NEXUS V2$(printf ' %.0s' {1..12})║${NC}"
echo -e "${CYAN}╠$(printf '═%.0s' {1..50})╣${NC}"

_report_line() {
  local label=$1 val=$2
  local color=$RED icon="✗"
  [[ "$val" == "OK" ]] && color=$GREEN && icon="✓"
  printf "${CYAN}║${NC}  ${color}${icon}${NC}  %-26s %s\n" "$label" "${color}${val}${NC}"
}

_report_line "Dependências Python"   "$R_DEPS"
_report_line "Ficheiro .env"         "$R_ENV"
_report_line "Systemd service"       "$R_SYSTEMD"
_report_line "Backend (servico)"     "$R_BACKEND"
_report_line "API REST (porta 8000)" "$R_API"
_report_line "WebSocket (porta 8001)" "$R_WS"
_report_line "Dashboard (porta 9000)" "$R_DASH"
echo -e "${CYAN}╚$(printf '═%.0s' {1..50})╝${NC}"
echo ""
echo "Logs em tempo real:"
echo "  journalctl -u nexus-backend -f"
echo "  journalctl -u nexus-backend -n 80 --no-pager"
echo ""

if [[ "$R_API" != "OK" ]]; then
  echo -e "${YELLOW}Próximos passos se a API ainda falhar:${NC}"
  echo "  1. journalctl -u nexus-backend -n 50 --no-pager"
  echo "  2. cd $NEXUS_HOME && PYTHONPATH=$NEXUS_HOME $PYTHON nexus/main.py"
  echo "  3. Copia o erro e partilha para diagnóstico adicional"
fi
