"""
NEXUS Market Monitor — Monitorização 24/7 de ativos
Cron jobs, alertas por email/SMS, análise automática.
"""
import os, json, threading, time, datetime, logging, urllib.request
logger = logging.getLogger('nexus.monitor')

# Modos de decisão
MODE_ASK = 'ask'       # Perguntar sempre antes de agir
MODE_AUTO = 'auto'     # Agir dentro dos limites sem perguntar

_monitor_thread = None
_monitor_running = False
_watched_assets = {}  # {symbol: {price_alert, drop_pct, rise_pct, ...}}


def get_price_yahoo(symbol):
    """Obtém preço via Yahoo Finance (grátis, sem key)."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        result = data['chart']['result'][0]
        meta = result['meta']
        return {
            'symbol': symbol,
            'price': meta.get('regularMarketPrice', 0),
            'prev_close': meta.get('previousClose', 0),
            'change_pct': round(
                ((meta.get('regularMarketPrice', 0) - meta.get('previousClose', 1)) /
                 meta.get('previousClose', 1)) * 100, 2
            ),
            'volume': meta.get('regularMarketVolume', 0),
            'currency': meta.get('currency', 'USD'),
            'market_state': meta.get('marketState', 'UNKNOWN')
        }, None
    except Exception as e:
        return None, f"Yahoo erro: {str(e)[:100]}"


def get_price_coingecko(coin_id):
    """Preço de cripto via CoinGecko (grátis)."""
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=eur,usd&include_24hr_change=true"
        req = urllib.request.Request(url, headers={'User-Agent': 'NEXUS/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if coin_id in data:
            d = data[coin_id]
            return {
                'symbol': coin_id,
                'price': d.get('eur', 0),
                'change_pct': d.get('eur_24h_change', 0),
                'currency': 'EUR'
            }, None
        return None, "Coin não encontrada"
    except Exception as e:
        return None, f"CoinGecko erro: {str(e)[:100]}"


def get_asset_price(symbol):
    """Router de preços — tenta Yahoo primeiro, depois CoinGecko para cripto."""
    crypto_ids = {'BTC': 'bitcoin', 'ETH': 'ethereum', 'SOL': 'solana', 'DOGE': 'dogecoin'}
    if symbol.upper() in crypto_ids:
        return get_price_coingecko(crypto_ids[symbol.upper()])
    return get_price_yahoo(symbol)


def save_watched_assets(user_id, db_path, assets):
    """Guarda lista de ativos vigiados."""
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT INTO memory (user_id, category, key, value, updated_at)
            VALUES (?, 'monitor', 'watched_assets', ?, datetime('now'))
            ON CONFLICT(user_id, category, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (user_id, json.dumps(assets)))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Save watched assets: {e}")


def load_watched_assets(user_id, db_path):
    """Carrega ativos vigiados do utilizador."""
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT value FROM memory WHERE user_id=? AND category='monitor' AND key='watched_assets'",
            (user_id,)
        ).fetchone()
        conn.close()
        return json.loads(row['value']) if row else {}
    except Exception:
        return {}


def get_monitor_config(user_id, db_path):
    """Carrega configuração de monitorização."""
    import sqlite3
    defaults = {
        'mode': MODE_ASK,
        'check_interval_min': 30,
        'drop_alert_pct': 2.0,
        'rise_alert_pct': 3.0,
        'max_ops_per_day': 3,
        'max_loss_per_day': 15.0,
        'max_loss_per_month': 50.0,
        'max_amount_per_op': 10.0,
        'allowed_asset_types': ['ETF', 'INDEX'],
        'email_alerts': True,
        'sms_alerts': False,
    }
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT value FROM memory WHERE user_id=? AND category='monitor' AND key='config'",
            (user_id,)
        ).fetchone()
        conn.close()
        if row:
            return {**defaults, **json.loads(row['value'])}
    except Exception:
        pass
    return defaults


def save_monitor_config(user_id, db_path, config):
    """Guarda configuração de monitorização."""
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT INTO memory (user_id, category, key, value, updated_at)
            VALUES (?, 'monitor', 'config', ?, datetime('now'))
            ON CONFLICT(user_id, category, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (user_id, json.dumps(config)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Save monitor config: {e}")
        return False


def save_alert(user_id, db_path, symbol, alert_type, message, price, change_pct):
    """Guarda alerta no histórico."""
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_alerts (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                symbol TEXT,
                alert_type TEXT,
                message TEXT,
                price REAL,
                change_pct REAL,
                sent INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "INSERT INTO market_alerts (user_id, symbol, alert_type, message, price, change_pct) VALUES (?,?,?,?,?,?)",
            (user_id, symbol, alert_type, message[:500], price, change_pct)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Save alert: {e}")


def get_recent_alerts(user_id, db_path, limit=20):
    """Retorna alertas recentes."""
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM market_alerts WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def build_alert_message(symbol, price_data, config, ai_fn=None):
    """Constrói mensagem de alerta com análise."""
    price = price_data.get('price', 0)
    change = price_data.get('change_pct', 0)
    direction = "📈 subiu" if change > 0 else "📉 caiu"

    alert_type = 'neutral'
    if change <= -config.get('drop_alert_pct', 2):
        alert_type = 'drop'
    elif change >= config.get('rise_alert_pct', 3):
        alert_type = 'rise'

    base_msg = f"**{symbol}** {direction} **{abs(change):.1f}%** hoje\nPreço atual: {price} {price_data.get('currency','')}"

    if ai_fn and alert_type != 'neutral':
        prompt = f"""O ativo {symbol} {direction} {abs(change):.1f}% hoje (preço: {price}).
        
        Analisa em 3 parágrafos curtos:
        1. Contexto e possível causa
        2. Se isto é oportunidade ou risco
        3. Recomendação clara para um iniciante com capital máximo de 10€
        
        Sê direto e honesto. Não exageres."""
        try:
            analysis, _ = ai_fn([{'role': 'user', 'content': prompt}], '')
            base_msg += f"\n\n**Análise:**\n{analysis}"
        except Exception:
            pass

    if config.get('mode') == MODE_ASK:
        base_msg += f"\n\n❓ **Queres agir?** Responde SIM ou NÃO no chat da NEXUS."

    return base_msg, alert_type


def check_all_assets(user_id, db_path, config, send_email_fn=None, ai_fn=None):
    """Verifica todos os ativos vigiados e gera alertas."""
    assets = load_watched_assets(user_id, db_path)
    if not assets:
        return []

    alerts_generated = []
    drop_threshold = config.get('drop_alert_pct', 2.0)
    rise_threshold = config.get('rise_alert_pct', 3.0)

    for symbol, asset_config in assets.items():
        price_data, err = get_asset_price(symbol)
        if err or not price_data:
            logger.warning(f"Preço {symbol}: {err}")
            continue

        change = price_data.get('change_pct', 0)
        price = price_data.get('price', 0)
        should_alert = False

        # Verifica thresholds
        if abs(change) >= drop_threshold and change < 0:
            should_alert = True
        elif change >= rise_threshold:
            should_alert = True

        # Verifica preço alvo personalizado
        target_low = asset_config.get('alert_below', 0)
        target_high = asset_config.get('alert_above', float('inf'))
        if target_low and price <= target_low:
            should_alert = True
        if target_high != float('inf') and price >= target_high:
            should_alert = True

        if should_alert:
            msg, alert_type = build_alert_message(symbol, price_data, config, ai_fn)
            save_alert(user_id, db_path, symbol, alert_type, msg, price, change)
            alerts_generated.append({'symbol': symbol, 'type': alert_type, 'change': change, 'price': price})

            # Envia email se configurado
            if send_email_fn and config.get('email_alerts'):
                email = os.environ.get('GMAIL_ADDRESS', '')
                if email:
                    try:
                        subject = f"🔔 NEXUS Alerta: {symbol} {'+' if change>0 else ''}{change:.1f}%"
                        send_email_fn(email, subject, msg)
                        logger.info(f"Alerta email enviado: {symbol}")
                    except Exception as e:
                        logger.error(f"Email alerta erro: {e}")

    return alerts_generated


class MarketMonitor:
    """Monitor de mercado em thread separada."""

    def __init__(self):
        self._running = False
        self._thread = None
        self._db_path = None
        self._send_email = None
        self._ai_fn = None
        self._user_configs = {}  # {user_id: config}

    def start(self, db_path, send_email_fn, ai_fn):
        self._db_path = db_path
        self._send_email = send_email_fn
        self._ai_fn = ai_fn
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Market Monitor iniciado")

    def is_running(self):
        return self._running and self._thread and self._thread.is_alive()

    def _loop(self):
        """Loop principal — verifica a cada N minutos."""
        while self._running:
            try:
                self._check_all_users()
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            time.sleep(30 * 60)  # 30 minutos por padrão

    def _check_all_users(self):
        """Verifica ativos de todos os utilizadores."""
        if not self._db_path:
            return
        import sqlite3
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            users = conn.execute("SELECT DISTINCT user_id FROM memory WHERE category='monitor'").fetchall()
            conn.close()
            for row in users:
                uid = row['user_id']
                config = get_monitor_config(uid, self._db_path)
                check_all_assets(uid, self._db_path, config, self._send_email, self._ai_fn)
        except Exception as e:
            logger.error(f"Check all users: {e}")

    def add_asset(self, user_id, db_path, symbol, config=None):
        """Adiciona ativo à lista de vigilância."""
        assets = load_watched_assets(user_id, db_path)
        assets[symbol.upper()] = config or {'alert_below': 0, 'alert_above': 0}
        save_watched_assets(user_id, db_path, assets)
        logger.info(f"Ativo adicionado: {symbol} para user {user_id}")

    def remove_asset(self, user_id, db_path, symbol):
        """Remove ativo da vigilância."""
        assets = load_watched_assets(user_id, db_path)
        assets.pop(symbol.upper(), None)
        save_watched_assets(user_id, db_path, assets)

    def force_check(self, user_id, db_path):
        """Força verificação imediata."""
        config = get_monitor_config(user_id, db_path)
        return check_all_assets(user_id, db_path, config, self._send_email, self._ai_fn)

    def stop(self):
        self._running = False


market_monitor = MarketMonitor()
