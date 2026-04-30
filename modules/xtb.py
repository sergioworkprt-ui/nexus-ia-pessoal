"""
NEXUS XTB Module — Integração com XTB broker
AVISO CRÍTICO: Este módulo executa ordens REAIS.
Requer autorização nível 3: WebAuthn + PIN + frase obrigatória.
"""
import json, logging, datetime, urllib.request, urllib.error
logger = logging.getLogger('nexus.xtb')

XTB_DEMO_URL = "wss://ws.xtb.com/demo"
XTB_REAL_URL = "wss://ws.xtb.com/real"

# ── HTTP REST fallback (xStation API) ────────────────────────────────────
XTB_API_BASE = "https://xapi.xtb.com"


def _xtb_request(endpoint, payload, token=None):
    """Faz request à API HTTP do XTB."""
    url = f"{XTB_API_BASE}{endpoint}"
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return None, str(e)[:200]


def xtb_login(account_id=None, password=None, mode=None):
    """
    Login XTB com diagnóstico de erros detalhado.
    mode: 'demo' (padrão e seguro) ou 'real' (requer autorização nível 3)
    """
    import os
    account_id = account_id or os.environ.get('XTB_ACCOUNT_ID', '')
    password = password or os.environ.get('XTB_PASSWORD', '')
    mode = mode or os.environ.get('XTB_MODE', 'demo')

    if not account_id:
        return None, "❌ XTB_ACCOUNT_ID não configurado no Render → Environment"
    if not password:
        return None, "❌ XTB_PASSWORD não configurado no Render → Environment"
    if mode not in ('demo', 'real'):
        return None, f"❌ XTB_MODE inválido: '{mode}'. Use 'demo' ou 'real'"

    payload = {
        "command": "login",
        "arguments": {
            "userId": account_id,
            "password": password,
            "appName": "NEXUS IA Pessoal"
        }
    }

    result, err = _xtb_request("/login", payload)

    if err:
        if "timeout" in str(err).lower():
            return None, "❌ Timeout — XTB API não responde. Tenta novamente."
        if "Name or service not known" in str(err) or "getaddrinfo" in str(err):
            return None, "❌ Erro de rede — sem acesso ao XTB. Verifica ligação."
        if "403" in str(err) or "401" in str(err):
            return None, "❌ Acesso negado (403/401) — credenciais inválidas ou conta bloqueada"
        if "404" in str(err):
            return None, "❌ Endpoint não encontrado (404) — API XTB pode ter mudado"
        return None, f"❌ Erro de rede: {err}"

    if not result:
        return None, "❌ Resposta vazia do XTB — API pode estar em manutenção"

    if result.get('status') == True:
        token = result.get('streamSessionId', '')
        if not token:
            return None, "❌ Login OK mas sem token de sessão — tenta novamente"
        logger.info(f"XTB login OK — conta: {account_id[:4]}*** modo: {mode}")
        return {
            'token': token,
            'mode': mode,
            'account': account_id,
            'logged_at': __import__('datetime').datetime.now().isoformat()
        }, None

    # Login falhou — diagnóstico
    error_code = result.get('errorCode', '')
    error_desc = result.get('errorDescr', str(result))
    if 'BE001' in error_code or 'Invalid' in error_desc:
        return None, "❌ ID ou password incorretos — verifica as credenciais XTB"
    if 'BE002' in error_code:
        return None, "❌ Conta bloqueada — contacta suporte XTB"
    if 'BE004' in error_code:
        return None, "❌ Sessão expirada — faz login novamente"
    return None, f"❌ Login rejeitado — código: {error_code} | {error_desc[:100]}"


def get_account_info(token):
    """Consulta saldo e informações da conta."""
    payload = {"command": "getMarginLevel", "streamSessionId": token}
    result, err = _xtb_request("/getMarginLevel", payload)
    if err: return None, err
    if result and result.get('status'):
        data = result.get('returnData', {})
        return {
            'balance': data.get('balance', 0),
            'equity': data.get('equity', 0),
            'margin': data.get('margin', 0),
            'free_margin': data.get('margin_free', 0),
            'currency': data.get('currency', 'EUR')
        }, None
    return None, "Erro ao consultar conta"


def get_positions(token):
    """Consulta posições abertas."""
    payload = {"command": "getTrades", "arguments": {"openedOnly": True}, "streamSessionId": token}
    result, err = _xtb_request("/getTrades", payload)
    if err: return [], err
    if result and result.get('status'):
        trades = result.get('returnData', [])
        return [{
            'symbol': t.get('symbol'),
            'volume': t.get('volume'),
            'open_price': t.get('open_price'),
            'profit': t.get('profit'),
            'sl': t.get('sl'),
            'tp': t.get('tp'),
            'cmd': 'BUY' if t.get('cmd') == 0 else 'SELL'
        } for t in trades], None
    return [], "Erro ao consultar posições"


def calculate_volume(symbol, amount_eur, price):
    """Calcula volume baseado em valor em euros."""
    if price <= 0: return 0.01  # mínimo
    volume = amount_eur / price
    return max(0.01, round(volume, 2))


def place_order(token, symbol, cmd, amount_eur, price, sl_points=50, tp_points=100,
                mode='demo', user_id=0, db_path=None):
    """
    Executa ordem real ou demo.
    OBRIGATÓRIO: autorização nível 3 antes de chamar esta função.
    """
    volume = calculate_volume(symbol, amount_eur, price)
    sl = round(price - (sl_points * 0.0001), 5) if cmd == 'BUY' else round(price + (sl_points * 0.0001), 5)
    tp = round(price + (tp_points * 0.0001), 5) if cmd == 'BUY' else round(price - (tp_points * 0.0001), 5)

    payload = {
        "command": "tradeTransaction",
        "arguments": {
            "tradeTransInfo": {
                "cmd": 0 if cmd == 'BUY' else 1,
                "symbol": symbol,
                "volume": volume,
                "price": price,
                "sl": sl,
                "tp": tp,
                "type": 0,  # open
                "comment": f"NEXUS {'REAL' if mode=='real' else 'DEMO'}"
            }
        },
        "streamSessionId": token
    }

    result, err = _xtb_request("/tradeTransaction", payload)

    # Log sempre
    if db_path:
        import sqlite3
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS xtb_orders (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    symbol TEXT, cmd TEXT, volume REAL,
                    price REAL, sl REAL, tp REAL,
                    amount_eur REAL, mode TEXT,
                    result TEXT, error TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute(
                "INSERT INTO xtb_orders (user_id,symbol,cmd,volume,price,sl,tp,amount_eur,mode,result,error) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, symbol, cmd, volume, price, sl, tp, amount_eur, mode,
                 json.dumps(result) if result else '', err or '')
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"XTB log error: {e}")

    if err: return None, f"Ordem falhou: {err}"
    if result and result.get('status'):
        order_id = result.get('returnData', {}).get('order', 0)
        logger.info(f"Ordem {cmd} {symbol} {volume} @ {price} — ID: {order_id} [{mode}]")
        return {'order_id': order_id, 'symbol': symbol, 'cmd': cmd,
                'volume': volume, 'price': price, 'sl': sl, 'tp': tp,
                'amount_eur': amount_eur, 'mode': mode}, None
    return None, f"Ordem rejeitada: {result}"


def close_position(token, order_id, symbol, volume, price, mode='demo'):
    """Fecha uma posição existente."""
    payload = {
        "command": "tradeTransaction",
        "arguments": {
            "tradeTransInfo": {
                "order": order_id,
                "cmd": 1,  # close
                "symbol": symbol,
                "volume": volume,
                "price": price,
                "type": 2,  # close
                "comment": "NEXUS CLOSE"
            }
        }
    }
    result, err = _xtb_request("/tradeTransaction", payload)
    if err: return None, err
    if result and result.get('status'):
        return {'closed': True, 'order_id': order_id}, None
    return None, f"Fecho falhou: {result}"


def get_symbol_price(token, symbol):
    """Consulta preço atual de um símbolo."""
    payload = {"command": "getSymbol", "arguments": {"symbol": symbol}}
    result, err = _xtb_request("/getSymbol", payload)
    if err: return None, err
    if result and result.get('status'):
        data = result.get('returnData', {})
        return {
            'symbol': symbol,
            'bid': data.get('bid', 0),
            'ask': data.get('ask', 0),
            'spread': data.get('spreadRaw', 0),
            'currency': data.get('currency', 'EUR')
        }, None
    return None, f"Símbolo não encontrado: {symbol}"


def get_xtb_orders_history(user_id, db_path, limit=20):
    """Histório de ordens da NEXUS."""
    import sqlite3
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
