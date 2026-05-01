"""
NEXUS Financial Module — Sistema financeiro inteligente com limites
AVISO: Este módulo é educativo e de simulação. Não executa ordens reais.
Qualquer ação real requer autorização nível 3 explícita do utilizador.
"""
import json, datetime, logging, sqlite3
logger = logging.getLogger('nexus.financial')

# Configuração padrão de limites
DEFAULT_CONFIG = {
    'max_loss_per_trade': 5.0,       # máximo de perda por operação (€)
    'profit_target': 20.0,           # meta de lucro para vender (€)
    'reinvest_amount': 10.0,         # valor a reinvestir (€)
    'withdraw_percent': 0.5,         # % a retirar como lucro (50%)
    'max_portfolio_risk': 0.02,      # 2% do portfolio por operação
    'protected_assets': ['SPY', 'VOO', 'VWCE', 'IWDA'],  # nunca vender sem ordem explícita
    'capital_initial': 10.0,         # capital inicial (€)
    'growth_mode': 'conservative',   # conservative / moderate / aggressive
}

RISK_WARNINGS = {
    'high_volatility': '⚠️ Alta volatilidade detetada. Risco aumentado.',
    'large_position': '⚠️ Posição grande relativamente ao capital.',
    'no_stop_loss': '⚠️ Sem stop-loss definido. Perdas ilimitadas possíveis.',
    'leverage': '⚠️ Alavancagem aumenta risco exponencialmente.',
    'crypto': '⚠️ Criptomoedas: risco extremo, volatilidade muito alta.',
    'penny_stock': '⚠️ Penny stocks: altamente manipuláveis e especulativas.',
}


def get_financial_config(user_id, db_path):
    """Carrega configuração financeira do utilizador."""
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT value FROM memory WHERE user_id=? AND category='financeiro' AND key='config'",
            (user_id,)
        ).fetchone()
        conn.close()
        if row:
            return {**DEFAULT_CONFIG, **json.loads(row['value'])}
        return DEFAULT_CONFIG.copy()
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_financial_config(user_id, db_path, config):
    """Guarda configuração financeira."""
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("""
            INSERT INTO memory (user_id, category, key, value, updated_at)
            VALUES (?, 'financeiro', 'config', ?, datetime('now'))
            ON CONFLICT(user_id, category, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (user_id, json.dumps(config)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Save config error: {e}")
        return False


def log_operation(user_id, db_path, op_type, asset, amount, price, result, notes=''):
    """Regista uma operação financeira."""
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS financial_ops (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                op_type TEXT,
                asset TEXT,
                amount REAL,
                price REAL,
                result REAL DEFAULT 0,
                notes TEXT,
                status TEXT DEFAULT 'simulated',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "INSERT INTO financial_ops (user_id, op_type, asset, amount, price, result, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, op_type, asset, amount, price, result, notes[:500])
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Log operation error: {e}")


def get_portfolio_summary(user_id, db_path):
    """Retorna resumo do portfolio simulado."""
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        ops = conn.execute(
            "SELECT * FROM financial_ops WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
            (user_id,)
        ).fetchall()
        conn.close()

        total_invested = sum(o['amount'] for o in ops if o['op_type'] == 'BUY')
        total_result = sum(o['result'] for o in ops)
        total_ops = len(ops)

        return {
            'total_invested': round(total_invested, 2),
            'total_result': round(total_result, 2),
            'total_ops': total_ops,
            'operations': [dict(o) for o in ops[:10]],
            'status': 'simulated'
        }
    except Exception:
        return {'total_invested': 0, 'total_result': 0, 'total_ops': 0, 'operations': [], 'status': 'no_data'}


def analyze_investment_plan(config, action, asset, amount):
    """
    Analisa um plano de investimento antes de executar.
    Retorna análise completa com riscos e recomendações.
    NUNCA executa — só analisa e apresenta para aprovação.
    """
    warnings = []
    recommendations = []
    risk_level = 'low'

    # Verifica limites
    if amount > config['max_loss_per_trade']:
        warnings.append(f"⚠️ Valor ({amount}€) excede limite de perda definido ({config['max_loss_per_trade']}€)")
        risk_level = 'high'

    # Ativos protegidos
    if asset.upper() in [a.upper() for a in config['protected_assets']]:
        if action == 'SELL':
            warnings.append(f"🛡️ {asset} é um ativo protegido. Venda bloqueada sem ordem explícita.")
            return {
                'allowed': False,
                'reason': f'{asset} está na lista de ativos protegidos',
                'warnings': warnings,
                'risk_level': 'blocked'
            }

    # Riscos específicos
    asset_upper = asset.upper()
    if any(c in asset_upper for c in ['BTC', 'ETH', 'USDT', 'SOL', 'DOGE']):
        warnings.append(RISK_WARNINGS['crypto'])
        risk_level = 'very_high'

    # Cálculo de reinvestimento
    reinvest_plan = None
    if action == 'SELL' and amount >= config['profit_target']:
        profit = amount - (amount * 0.1)  # estimativa
        reinvest = config['reinvest_amount']
        withdraw = profit * config['withdraw_percent']
        reinvest_plan = {
            'reinvest': reinvest,
            'withdraw': round(withdraw, 2),
            'keep': round(profit - reinvest - withdraw, 2)
        }

    # Recomendações
    if risk_level in ['high', 'very_high']:
        recommendations.append(f"💡 Considera reduzir para {config['max_loss_per_trade']}€ máximo")
    if not any(p in asset_upper for p in ['SPY', 'VOO', 'VWCE', 'IWDA']):
        recommendations.append("💡 ETFs de índice (S&P500, MSCI World) são mais seguros para iniciantes")

    return {
        'allowed': len([w for w in warnings if '🛡️' in w]) == 0,
        'action': action,
        'asset': asset,
        'amount': amount,
        'risk_level': risk_level,
        'warnings': warnings,
        'recommendations': recommendations,
        'reinvest_plan': reinvest_plan,
        'config': {
            'max_loss': config['max_loss_per_trade'],
            'profit_target': config['profit_target'],
            'protected': config['protected_assets']
        },
        'status': 'ANALYSIS_ONLY — requer AUTORIZO EXECUÇÃO REAL para prosseguir'
    }


def fact_check_investment_claim(claim, ai_fn):
    """
    Fact-check de afirmações de investimento.
    Compara com conhecimento real e identifica exageros.
    """
    prompt = f"""Faz um fact-check rigoroso desta afirmação sobre investimento:

"{claim}"

Analisa e responde com:
1. **VEREDICTO**: Verdadeiro / Falso / Enganoso / Exagerado / Parcialmente verdadeiro
2. **RISCOS ESCONDIDOS**: lista os riscos que não foram mencionados
3. **O QUE É REALISTA**: o que de facto é possível
4. **O QUE É EXAGERO**: o que é improvável ou impossível
5. **RECOMENDAÇÃO**: o que deve o investidor saber antes de agir

Sê direto, objetivo e usa dados reais. Protege o utilizador de promessas falsas."""

    messages = [{'role': 'user', 'content': prompt}]
    response, model = ai_fn(messages, '')
    return {'fact_check': response, 'model': model, 'claim': claim}
