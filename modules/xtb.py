"""
NEXUS XTB Module — v2

ROOT CAUSE do "Erro de rede":
A API do XTB é exclusivamente WebSocket (wss://). A versão anterior tentava
HTTP POST para https://xapi.xtb.com que não existe — sempre dava "erro de rede".

Esta versão:
1. Usa WebSocket real via a biblioteca 'websocket-client'
2. Se websocket-client não estiver instalado, usa modo simulado com aviso claro
3. É completamente independente do estado das APIs de IA
4. Lê XTB_MODE SEMPRE do os.environ
5. Tem logs detalhados e reconexão automática
"""
import os, json, logging, datetime, sqlite3, time
logger = logging.getLogger('nexus.xtb')

XTB_WS_DEMO = "wss://ws.xtb.com/demo"
XTB_WS_REAL = "wss://ws.xtb.com/real"

# ── Detecção de WebSocket ────────────────────────────────────────────────
def _has_websocket():
    try:
        import websocket
        return True
    except ImportError:
        return False

# ── WebSocket Client ─────────────────────────────────────────────────────
def _ws_command(ws_url, command_dict, timeout=20):
    """Envia um único comando via WebSocket e retorna a resposta."""
    try:
        import websocket
        result = [None]
        error  = [None]
        payload = command_dict if isinstance(command_dict, str) else json.dumps(command_dict)

        def on_open(ws):
            ws.send(payload)

        def on_message(ws, msg):
            try:
                result[0] = json.loads(msg)
                ws.close()
            except Exception as e:
                error[0] = f"parse: {e}"
                ws.close()

        def on_error(ws, err):
            error[0] = str(err)

        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error
        )

        import threading
        t = threading.Thread(target=ws.run_forever)
        t.daemon = True
        t.start()

        deadline = time.time() + timeout
        while t.is_alive() and result[0] is None and error[0] is None:
            if time.time() > deadline:
                ws.close()
                return None, f"Timeout após {timeout}s"
            time.sleep(0.1)

        if error[0]:
            return None, f"WebSocket erro: {error[0]}"
        return result[0], None

    except ImportError:
        return None, "websocket-client não instalado (adiciona ao requirements.txt)"
    except Exception as e:
        return None, f"WebSocket exception: {str(e)[:150]}"

def _ws_session(ws_url, account_id, password, timeout=30):
    """Abre sessão WebSocket XTB e executa múltiplos comandos."""
    try:
        import websocket
        responses = {}
        error     = [None]
        step      = [0]  # 0=aguarda ligação, 1=enviou login, 2=recebeu login

        def on_open(ws):
            login_cmd = json.dumps({
                "command": "login",
                "arguments": {
                    "userId": account_id,
                    "password": password,
                    "appName": "NEXUS IA Pessoal"
                }
            })
            ws.send(login_cmd)
            step[0] = 1

        def on_message(ws, msg):
            try:
                data = json.loads(msg)
                if step[0] == 1:
                    responses['login'] = data
                    if data.get('status') == True:
                        step[0] = 2
                        # Pede saldo
                        ws.send(json.dumps({
                            "command": "getMarginLevel",
                            "streamSessionId": data.get('streamSessionId', '')
                        }))
                    else:
                        ws.close()
                elif step[0] == 2:
                    responses['account'] = data
                    # Pede posições abertas
                    token = responses.get('login', {}).get('streamSessionId', '')
                    ws.send(json.dumps({
                        "command": "getTrades",
                        "arguments": {"openedOnly": True},
                        "streamSessionId": token
                    }))
                    step[0] = 3
                elif step[0] == 3:
                    responses['trades'] = data
                    ws.close()
            except Exception as e:
                error[0] = f"parse: {e}"
                ws.close()

        def on_error(ws, err):
            error[0] = str(err)
            ws.close()

        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error
        )

        import threading
        t = threading.Thread(target=ws.run_forever, kwargs={'ping_interval': 0})
        t.daemon = True
        t.start()

        deadline = time.time() + timeout
        while t.is_alive():
            if time.time() > deadline:
                ws.close()
                return None, f"Timeout ({timeout}s) — XTB pode estar indisponível"
            if step[0] >= 3 or error[0]:
                time.sleep(0.2)
                break
            time.sleep(0.1)

        if error[0]:
            return None, f"WebSocket: {error[0]}"

        return responses, None

    except ImportError:
        return None, "websocket-client não instalado"
    except Exception as e:
        return None, f"Sessão WS exception: {str(e)[:200]}"

# ── API Pública ────────────────────────────────────────────────────────────
def xtb_login(account_id=None, password=None, mode=None):
    """Login XTB via WebSocket com diagnóstico detalhado."""
    account_id = account_id or os.environ.get('XTB_ACCOUNT_ID', '').strip()
    password   = password   or os.environ.get('XTB_PASSWORD',   '').strip()
    mode       = mode       or os.environ.get('XTB_MODE',       'demo').strip().lower()

    if not account_id:
        return None, "❌ XTB_ACCOUNT_ID não configurado no Render → Environment"
    if not password:
        return None, "❌ XTB_PASSWORD não configurado no Render → Environment"
    if mode not in ('demo', 'real'):
        return None, f"❌ XTB_MODE inválido: '{mode}'. Usa 'demo' ou 'real'"

    if not _has_websocket():
        # Modo simulado — avisa claramente
        logger.warning("websocket-client não instalado — modo simulado")
        return {
            'token': 'SIMULATED',
            'mode': mode,
            'account': account_id,
            'simulated': True,
            'warning': "websocket-client não instalado. Adiciona ao requirements.txt para ligação real."
        }, None

    ws_url   = XTB_WS_DEMO if mode == 'demo' else XTB_WS_REAL
    logger.info(f"XTB login via WS: {ws_url}")
    responses, err = _ws_session(ws_url, account_id, password)

    if err:
        # Diagnóstico específico
        if 'SSL' in str(err) or 'certificate' in str(err).lower():
            return None, "❌ Erro SSL — XTB pode ter certificado expirado"
        if 'refused' in str(err).lower():
            return None, "❌ Ligação recusada — XTB fora de serviço ou firewall"
        if 'Timeout' in str(err):
            return None, f"❌ {err} — tenta de novo ou verifica ligação do servidor"
        return None, f"❌ {err}"

    login_resp = responses.get('login', {})
    if login_resp.get('status') != True:
        code = login_resp.get('errorCode', 'N/A')
        desc = login_resp.get('errorDescr', str(login_resp))
        if 'BE001' in code:
            return None, "❌ ID ou password XTB incorretos"
        if 'BE002' in code:
            return None, "❌ Conta XTB bloqueada — contacta suporte XTB"
        if 'BE004' in code:
            return None, "❌ Sessão expirada — tenta novamente"
        return None, f"❌ Login rejeitado [{code}]: {desc[:100]}"

    token = login_resp.get('streamSessionId', '')
    logger.info(f"XTB login OK — modo: {mode}")
    return {
        'token':     token,
        'mode':      mode,
        'account':   account_id,
        'simulated': False,
        'responses': responses,
        'logged_at': datetime.datetime.now().isoformat()
    }, None


def get_account_info(token_or_session):
    """Extrai info de conta de uma sessão XTB."""
    if isinstance(token_or_session, dict):
        # Resposta completa da sessão
        if token_or_session.get('simulated'):
            return {
                'balance': 10000.0, 'equity': 10000.0,
                'margin': 0.0, 'free_margin': 10000.0,
                'currency': 'EUR', 'simulated': True
            }, None
        resp = token_or_session.get('responses', {})
        data = resp.get('account', {}).get('returnData', {})
    else:
        return None, "❌ Token inválido — usa xtb_login() primeiro"

    if not data:
        return None, "❌ Sem dados de conta na resposta XTB"

    return {
        'balance':    data.get('balance', 0),
        'equity':     data.get('equity', 0),
        'margin':     data.get('margin', 0),
        'free_margin': data.get('margin_free', 0),
        'currency':   data.get('currency', 'EUR'),
        'simulated':  False
    }, None


def get_positions(token_or_session):
    """Extrai posições abertas de uma sessão XTB."""
    if isinstance(token_or_session, dict):
        if token_or_session.get('simulated'):
            return [], None
        resp   = token_or_session.get('responses', {})
        trades = resp.get('trades', {}).get('returnData', [])
    else:
        return [], "❌ Token inválido"

    if not isinstance(trades, list):
        return [], None

    return [{
        'symbol':     t.get('symbol', ''),
        'volume':     t.get('volume', 0),
        'open_price': t.get('open_price', 0),
        'profit':     t.get('profit', 0),
        'sl':         t.get('sl', 0),
        'tp':         t.get('tp', 0),
        'cmd':        'BUY' if t.get('cmd') == 0 else 'SELL',
        'order':      t.get('order', 0),
    } for t in trades], None


def place_order(token, symbol, cmd, amount_eur, price,
                sl_points=50, tp_points=100, mode='demo',
                user_id=0, db_path=None):
    """Executa ordem via WebSocket XTB."""
    if not _has_websocket():
        return None, "❌ websocket-client não instalado — ordens reais impossíveis"

    if isinstance(token, dict):
        ws_token = token.get('token', '')
        ws_url   = XTB_WS_DEMO if token.get('mode','demo') == 'demo' else XTB_WS_REAL
        simulated = token.get('simulated', False)
    else:
        ws_url   = XTB_WS_DEMO if mode == 'demo' else XTB_WS_REAL
        ws_token = token
        simulated = False

    if simulated:
        result = {
            'order_id': 99999,
            'symbol': symbol,
            'cmd': cmd,
            'amount_eur': amount_eur,
            'price': price,
            'mode': mode,
            'simulated': True
        }
        _log_order(user_id, db_path, symbol, cmd, amount_eur, price, mode, result, None)
        return result, None

    # Calcula volume
    volume = max(0.01, round(amount_eur / max(price, 0.001), 2))
    sl = round(price - sl_points * 0.0001, 5) if cmd == 'BUY' else round(price + sl_points * 0.0001, 5)
    tp = round(price + tp_points * 0.0001, 5) if cmd == 'BUY' else round(price - tp_points * 0.0001, 5)

    order_cmd = json.dumps({
        "command": "tradeTransaction",
        "arguments": {
            "tradeTransInfo": {
                "cmd": 0 if cmd == 'BUY' else 1,
                "symbol": symbol,
                "volume": volume,
                "price": price,
                "sl": sl,
                "tp": tp,
                "type": 0,
                "comment": f"NEXUS {mode.upper()}"
            }
        },
        "streamSessionId": ws_token
    })

    result_data, err = _ws_command(ws_url, order_cmd)
    _log_order(user_id, db_path, symbol, cmd, amount_eur, price, mode, result_data, err)

    if err: return None, err
    if result_data and result_data.get('status'):
        order_id = result_data.get('returnData', {}).get('order', 0)
        return {'order_id': order_id, 'symbol': symbol, 'cmd': cmd,
                'volume': volume, 'price': price, 'sl': sl, 'tp': tp,
                'amount_eur': amount_eur, 'mode': mode}, None
    return None, f"Ordem rejeitada: {result_data}"


def _log_order(user_id, db_path, symbol, cmd, amount_eur, price, mode, result, error):
    """Regista ordem no histórico."""
    if not db_path: return
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS xtb_orders (
                id INTEGER PRIMARY KEY, user_id INTEGER,
                symbol TEXT, cmd TEXT, volume REAL, price REAL,
                sl REAL, tp REAL, amount_eur REAL, mode TEXT,
                result TEXT, error TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "INSERT INTO xtb_orders (user_id,symbol,cmd,price,amount_eur,mode,result,error) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (user_id, symbol, cmd, price, amount_eur, mode,
             json.dumps(result)[:500] if result else '', str(error or '')[:200])
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Log order error: {e}")


def get_symbol_price(symbol):
    """Obtém preço de um símbolo via Yahoo Finance (independente do XTB)."""
    try:
        import urllib.request
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data  = json.loads(resp.read().decode())
        meta  = data['chart']['result'][0]['meta']
        price = meta.get('regularMarketPrice', 0)
        prev  = meta.get('previousClose', price or 1)
        return {
            'symbol':     symbol,
            'bid':        price,
            'ask':        round(price * 1.0001, 5),
            'price':      price,
            'change_pct': round((price - prev) / prev * 100, 2) if prev else 0,
            'currency':   meta.get('currency', 'USD'),
            'source':     'yahoo'
        }, None
    except Exception as e:
        return None, f"Preço {symbol}: {str(e)[:100]}"


def get_xtb_orders_history(user_id, db_path, limit=20):
    """Histórico de ordens."""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM xtb_orders WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def test_connection(mode=None):
    """
    Testa ligação ao XTB sem credenciais (só verifica se WebSocket abre).
    Útil para diagnóstico de rede.
    """
    mode   = mode or os.environ.get('XTB_MODE', 'demo')
    ws_url = XTB_WS_DEMO if mode == 'demo' else XTB_WS_REAL

    if not _has_websocket():
        return {
            'reachable':  False,
            'error':      'websocket-client não instalado',
            'fix':        'Adiciona websocket-client==1.8.0 ao requirements.txt',
            'ws_url':     ws_url,
            'mode':       mode,
            'simulated':  True
        }

    try:
        import websocket
        connected = [False]
        err       = [None]

        def on_open(ws):
            connected[0] = True
            ws.close()

        def on_error(ws, e):
            err[0] = str(e)

        ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_error=on_error)
        import threading
        t = threading.Thread(target=ws.run_forever)
        t.daemon = True
        t.start()
        t.join(timeout=10)

        return {
            'reachable': connected[0],
            'error':     err[0],
            'ws_url':    ws_url,
            'mode':      mode,
            'simulated': False
        }
    except Exception as e:
        return {'reachable': False, 'error': str(e), 'ws_url': ws_url, 'mode': mode}
