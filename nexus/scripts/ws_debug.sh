#!/usr/bin/env bash
# ws_debug.sh — Diagnóstico completo do WebSocket do NEXUS
# Escreve tudo para /tmp/nexus_ws_debug.txt E para stdout.
# Uso: sudo bash /opt/nexus/nexus/scripts/ws_debug.sh

NEXUS_HOME="/opt/nexus"
VENV="$NEXUS_HOME/venv"
PY="$VENV/bin/python"
LOG="/tmp/nexus_ws_debug.txt"

exec > >(tee "$LOG") 2>&1  # tee: mostra E grava para ficheiro

echo "====================================="
echo " NEXUS WS Debug  $(date)  "
echo "====================================="
echo ""

echo "--- 1. Python e venv ---"
"$PY" --version 2>&1 || echo "ERRO: $PY não encontrado"
echo "PATH=$PATH"
echo ""

echo "--- 2. websockets ---"
"$PY" -c "import websockets; print('websockets', websockets.__version__)" 2>&1
echo ""

echo "--- 3. nexus-ws.service ---"
cat /etc/systemd/system/nexus-ws.service 2>/dev/null || echo "FICHEIRO NÃO EXISTE"
echo ""

echo "--- 4. systemctl status nexus-ws ---"
systemctl status nexus-ws --no-pager -l 2>&1 || echo "(sem estado)"
echo ""

echo "--- 5. journal nexus-ws (sem -f) ---"
journalctl -u nexus-ws -n 50 --no-pager 2>&1 || echo "(vazio)"
echo ""

echo "--- 6. Ports abertas ---"
ss -tulpn 2>/dev/null | grep -E ":800[0-9]|:9000" || echo "(nenhuma porta nexus)"
echo ""

echo "--- 7. ws_server.py (primeiras 20 linhas) ---"
head -20 "$NEXUS_HOME/nexus/ws_server.py" 2>/dev/null || echo "FICHEIRO NÃO ENCONTRADO"
echo ""

echo "--- 8. git log -5 ---"
cd "$NEXUS_HOME" && git log --oneline -5 2>/dev/null || echo "(não é repo git)"
echo ""

# Teste Python inline: escreve para /tmp, não precisa de journal
echo "--- 9. TESTE INLINE websockets (output em $LOG) ---"

TEST_LOG="/tmp/nexus_ws_inline_$(date +%s).log"
echo "A escrever para: $TEST_LOG"

timeout 8 "$PY" - 2>&1 | tee -a "$LOG" <<'PYEOF'
import sys, os, asyncio

LOG_FILE = "/tmp/nexus_ws_inline.log"

def log(msg):
    line = msg + "\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    with open(LOG_FILE, "a") as f:
        f.write(line)

log(f"[TEST] Python: {sys.executable}")
log(f"[TEST] WS_HOST: {os.getenv('WS_HOST', '0.0.0.0')}")
log(f"[TEST] WS_PORT: {os.getenv('WS_PORT', '8001')}")

HOST = os.getenv("WS_HOST", "0.0.0.0")
PORT = int(os.getenv("WS_PORT", "8001"))

try:
    import websockets
    log(f"[TEST] websockets {websockets.__version__} importado OK")
except Exception as e:
    log(f"[TEST] ERRO import websockets: {e}")
    sys.exit(1)

async def handler(ws):
    log(f"[TEST] cliente ligado!")
    await ws.close()

async def main():
    log(f"[TEST] A chamar websockets.serve on {HOST}:{PORT}...")
    try:
        async with websockets.serve(handler, HOST, PORT):
            log(f"[TEST] PORTA {PORT} ABERTA! WebSocket online.")
            await asyncio.sleep(5)
    except Exception as e:
        import traceback
        log(f"[TEST] ERRO: {type(e).__name__}: {e}")
        traceback.print_exc()
    log("[TEST] Terminou.")

asyncio.run(main())
PYEOF

echo ""
echo "====================================="
echo " Ficheiro de log: $LOG             "
echo " Ficheiro inline: /tmp/nexus_ws_inline.log"
echo "====================================="
echo ""
echo "Para ver:"
echo "  cat $LOG"
echo "  cat /tmp/nexus_ws_inline.log"
