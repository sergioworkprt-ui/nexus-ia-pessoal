"""
NEXUS XTB Module — v4

Mudanças vs v3:
- Suporte a proxy SOCKS5/HTTP via variável XTB_PROXY (ex: socks5://user:pass@host:port)
- Mensagem clara quando XTB bloqueia IPs de datacenter (403 host_not_allowed)
- create_connection síncrono com headers corretos (Origin, User-Agent)
- SSL verify desativado (necessário em datacenters como o Render)
"""
import os, json, logging, datetime, sqlite3, time
from urllib.parse import urlparse
logger = logging.getLogger('nexus.xtb')

XTB_WS_DEMO = "wss://ws.xtb.com/demo"
XTB_WS_REAL = "wss://ws.xtb.com/real"

_ERR_IP_BLOCKED = (
    "❌ XTB bloqueou o IP do servidor (403 host_not_allowed).\n"
    "O XTB proíbe ligações de IPs de datacenters (Render, AWS, etc.).\n"
    "Solução: define XTB_PROXY=socks5://user:pass@host:port no Render → Environment "
    "apontando para um proxy residencial ou VPS com IP doméstico/empresarial."
)

# ── Detecção de WebSocket ─────────────────────────────────────────────────
def _has_websocket():
    try:
        import websocket
        return True
    except ImportError:
        return False


def _parse_proxy(proxy_url):
    """Extrai (host, port, type, user, pass) de uma URL de proxy."""
    p = urlparse(proxy_url)
    proxy_type = p.scheme.lower()  # socks5, socks4, http, https
    if proxy_type == 'https':
        proxy_type = 'http'
    return {
        'http_proxy_host': p.hostname,
        'http_proxy_port': p.port or (1080 if 'socks' in proxy_type else 3128),
        'proxy_type':      proxy_type,
        'http_proxy_auth': (p.username, p.password) if p.username else None,
    }


# ── Ligação síncrona (create_connection) ──────────────────────────────────
def _ws_connect(mode, timeout=20):
    """Cria ligação WebSocket síncrona ao XTB. Suporta proxy via XTB_PROXY."""
    import websocket, ssl

    ws_url   = XTB_WS_DEMO if mode == 'demo' else XTB_WS_REAL
    ssl_opts = {"cert_reqs": ssl.CERT_NONE}
    headers  = [
        "Origin: https://www.xtb.com",
        "User-Agent: Mozilla/5.0 NEXUS/1.0",
    ]

    proxy_url = os.environ.get('XTB_PROXY', '').strip()
    proxy_kwargs = _parse_proxy(proxy_url) if proxy_url else {}

    if proxy_url:
        logger.info(f"XTB WS via proxy: {proxy_kwargs.get('http_proxy_host')}:{proxy_kwargs.get('http_proxy_port')}")

    try:
        ws = websocket.create_connection(
            ws_url,
            timeout=timeout,
            sslopt=ssl_opts,
            header=headers,
            **proxy_kwargs,
        )
        logger.info(f"XTB WS ligado: {ws_url}")
        return ws, None
    except Exception as e:
        err = str(e)
        if '403' in err or 'host_not_allowed' in err or 'Forbidden' in err:
            return None, _ERR_IP_BLOCKED
        if '404' in err or 'Not Found' in err:
            return None, (
                f"XTB endpoint não encontrado (404) — "
                f"ws.xtb.com/{mode} pode ter mudado de URL ou estar em manutenção"
            )
        if 'timed out' in err.lower() or 'timeout' in err.lower():
            return None, f"Timeout ({timeout}s) ao ligar ao XTB — servidor pode estar sobrecarregado"
        if 'refused' in err.lower():
            return None, "Ligação recusada — XTB fora de serviço ou firewall"
        return None, err[:200]


def _ws_send_recv(ws, cmd_dict, label='', timeout=15):
    """Envia comando JSON e retorna resposta parseada."""
    try:
        ws.settimeout(timeout)
        ws.send(json.dumps(cmd_dict))
        resp = ws.recv()
        return json.loads(resp), None
    except Exception as e:
        return None, f"{label or 'cmd'}: {str(e)[:150]}"


def _ws_session_sync(mode, account_id, password, timeout=30):
    """
    Abre sessão XTB síncrona: login → saldo → posições.
    Retorna (responses_dict, error).
    """
    ws, err = _ws_connect(mode, timeout=timeout)
    if err:
        return None, err

    responses = {}
    try:
        # 1. Login
        resp, err = _ws_send_recv(ws, {
            "command": "login",
            "arguments": {
                "userId":   account_id,
                "password": password,
                "appName":  "NEXUS IA Pessoal"
            }
        }, "login", timeout=20)
        if err:
            return None, f"Login WS: {err}"
        responses['login'] = resp

        if not resp or resp.get('status') != True:
            code = resp.get('errorCode', '') if resp else ''
            desc = resp.get('errorDescr', str(resp)) if resp else 'sem resposta'
            return None, f"login_rejected:{code}:{desc}"

        stream_id = resp.get('streamSessionId', '')

        # 2. Saldo
        resp2, err2 = _ws_send_recv(ws, {
            "command":         "getMarginLevel",
            "streamSessionId": stream_id
        }, "getMarginLevel", timeout=15)
        if not err2:
            responses['account'] = resp2

        # 3. Posições abertas
        resp3, err3 = _ws_send_recv(ws, {
            "command":         "getTrades",
            "arguments":       {"openedOnly": True},
            "streamSessionId": stream_id
        }, "getTrades", timeout=15)
        if not err3:
            responses['trades'] = resp3

    finally:
        try:
            ws.close()
        except Exception:
            pass

    return responses, None


# ── API Pública ────────────────────────────────────────────────────────────
def xtb_login(account_id=None, password=None, mode=None):
    """Login XTB com diagnóstico detalhado."""
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
        logger.warning("websocket-client não instalado — modo simulado")
        return {
            'token':     'SIMULATED',
            'mode':      mode,
            'account':   account_id,
            'simulated': True,
            'warning':   "websocket-client não instalado. Adiciona websocket-client ao requirements.txt."
        }, None

    logger.info(f"XTB login — modo: {mode}")
    responses, err = _ws_session_sync(mode, account_id, password)

    if err:
        if err.startswith('login_rejected:'):
            _, code, desc = err.split(':', 2)
            if 'BE001' in code: return None, "❌ ID ou password XTB incorretos"
            if 'BE002' in code: return None, "❌ Conta XTB bloqueada — contacta suporte XTB"
            if 'BE004' in code: return None, "❌ Sessão expirada — tenta novamente"
            return None, f"❌ Login rejeitado [{code}]: {desc[:100]}"
        if '404' in err:
            return None, f"❌ {err}"
        if 'Timeout' in err or 'timeout' in err:
            return None, f"❌ {err}"
        return None, f"❌ Erro de ligação XTB: {err}"

    login_resp = responses.get('login', {})
    token      = login_resp.get('streamSessionId', '')
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
    if not isinstance(token_or_session, dict):
        return None, "❌ Token inválido — usa xtb_login() primeiro"

    if token_or_session.get('simulated'):
        return {
            'balance': 10000.0, 'equity': 10000.0,
            'margin': 0.0, 'free_margin': 10000.0,
            'currency': 'EUR', 'simulated': True
        }, None

    resp  = token_or_session.get('responses', {})
    data  = resp.get('account', {}).get('returnData', {})

    if not data:
        return None, "❌ Sem dados de conta na resposta XTB"

    return {
        'balance':     data.get('balance', 0),
        'equity':      data.get('equity', 0),
        'margin':      data.get('margin', 0),
        'free_margin': data.get('margin_free', 0),
        'currency':    data.get('currency', 'EUR'),
        'simulated':   False
    }, None


def get_positions(token_or_session):
    """Extrai posições abertas de uma sessão XTB."""
    if not isinstance(token_or_session, dict):
        return [], "❌ Token inválido"

    if token_or_session.get('simulated'):
        return [], None

    resp   = token_or_session.get('responses', {})
    trades = resp.get('trades', {}).get('returnData', [])

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
        ws_token  = token.get('token', '')
        order_mode = token.get('mode', 'demo')
        simulated  = token.get('simulated', False)
    else:
        order_mode = mode
        ws_token   = token
        simulated  = False

    if simulated:
        result = {
            'order_id': 99999, 'symbol': symbol, 'cmd': cmd,
            'amount_eur': amount_eur, 'price': price, 'mode': order_mode, 'simulated': True
        }
        _log_order(user_id, db_path, symbol, cmd, amount_eur, price, order_mode, result, None)
        return result, None

    volume = max(0.01, round(amount_eur / max(price, 0.001), 2))
    sl     = round(price - sl_points * 0.0001, 5) if cmd == 'BUY' else round(price + sl_points * 0.0001, 5)
    tp     = round(price + tp_points * 0.0001, 5) if cmd == 'BUY' else round(price - tp_points * 0.0001, 5)

    ws, err = _ws_connect(order_mode)
    if err:
        return None, f"❌ Ligação falhou: {err}"

    try:
        resp, err2 = _ws_send_recv(ws, {
            "command": "tradeTransaction",
            "arguments": {
                "tradeTransInfo": {
                    "cmd": 0 if cmd == 'BUY' else 1,
                    "symbol": symbol, "volume": volume,
                    "price": price, "sl": sl, "tp": tp,
                    "type": 0, "comment": f"NEXUS {order_mode.upper()}"
                }
            },
            "streamSessionId": ws_token
        }, "tradeTransaction")
    finally:
        try: ws.close()
        except Exception: pass

    _log_order(user_id, db_path, symbol, cmd, amount_eur, price, order_mode, resp, err2)

    if err2:
        return None, err2
    if resp and resp.get('status'):
        order_id = resp.get('returnData', {}).get('order', 0)
        return {
            'order_id': order_id, 'symbol': symbol, 'cmd': cmd,
            'volume': volume, 'price': price, 'sl': sl, 'tp': tp,
            'amount_eur': amount_eur, 'mode': order_mode
        }, None
    return None, f"Ordem rejeitada: {resp}"


def close_position(token, order_id, symbol, volume, price, mode='demo'):
    """Fecha uma posição aberta via WebSocket XTB."""
    if not _has_websocket():
        return None, "❌ websocket-client não instalado"

    if isinstance(token, dict):
        ws_token   = token.get('token', '')
        close_mode = token.get('mode', 'demo')
        simulated  = token.get('simulated', False)
    else:
        close_mode = mode
        ws_token   = token
        simulated  = False

    if simulated:
        return {
            'closed': True, 'order_id': order_id,
            'symbol': symbol, 'volume': volume, 'price': price, 'simulated': True
        }, None

    ws, err = _ws_connect(close_mode)
    if err:
        return None, f"❌ Ligação falhou: {err}"

    try:
        resp, err2 = _ws_send_recv(ws, {
            "command": "tradeTransaction",
            "arguments": {
                "tradeTransInfo": {
                    "cmd": 2, "order": order_id, "symbol": symbol,
                    "volume": volume, "price": price, "type": 2,
                    "comment": f"NEXUS CLOSE {close_mode.upper()}"
                }
            },
            "streamSessionId": ws_token
        }, "closePosition")
    finally:
        try: ws.close()
        except Exception: pass

    if err2:
        return None, err2
    if resp and resp.get('status'):
        closed_id = resp.get('returnData', {}).get('order', order_id)
        return {
            'closed': True, 'order_id': closed_id, 'symbol': symbol,
            'volume': volume, 'price': price, 'mode': close_mode
        }, None
    return None, f"Falha ao fechar posição: {resp}"


def _log_order(user_id, db_path, symbol, cmd, amount_eur, price, mode, result, error):
    """Regista ordem no histórico."""
    if not db_path: return
    try:
        conn = sqlite3.connect(db_path, timeout=30)
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
        conn = sqlite3.connect(db_path, timeout=30)
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
    """Testa ligação ao XTB sem credenciais."""
    mode = mode or os.environ.get('XTB_MODE', 'demo')

    if not _has_websocket():
        return {
            'reachable': False,
            'error':     'websocket-client não instalado',
            'fix':       'Adiciona websocket-client ao requirements.txt',
            'mode':      mode,
            'simulated': True
        }

    ws, err = _ws_connect(mode, timeout=10)
    if ws:
        try: ws.close()
        except Exception: pass
        return {'reachable': True, 'error': None, 'mode': mode, 'simulated': False}
    return {'reachable': False, 'error': err, 'mode': mode, 'simulated': False}
