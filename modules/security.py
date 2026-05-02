from modules.database import get_db
"""
NEXUS Security Module — Autorização multinível
Nível 1: análise/simulação (sem autorização)
Nível 2: alterações internas (confirmação simples)
Nível 3: ações financeiras reais (WebAuthn + PIN + frase)
"""
import hashlib, datetime, json, logging, os
logger = logging.getLogger('nexus.security')

# Frases obrigatórias para nível 3
AUTH_PHRASES = {
    'execute': 'AUTORIZO EXECUÇÃO REAL',
    'production': 'AUTORIZO ALTERAÇÃO EM PRODUÇÃO',
}
EMERGENCY_STOP_PHRASE = 'NEXUS, parar imediatamente todas as ações reais.'

# Estado de emergência global
_emergency_stop = False
_emergency_time = None


def emergency_stop(user_id, db_path):
    global _emergency_stop, _emergency_time
    _emergency_stop = True
    _emergency_time = datetime.datetime.now().isoformat()
    audit_log(user_id, 'EMERGENCY_STOP', 'Travão de emergência ativado', db_path, level=3)
    logger.warning(f"EMERGENCY STOP ativado por user {user_id}")
    return {'ok': True, 'stopped': True, 'time': _emergency_time}


def emergency_resume(user_id, db_path):
    global _emergency_stop, _emergency_time
    _emergency_stop = False
    _emergency_time = None
    audit_log(user_id, 'EMERGENCY_RESUME', 'Sistema retomado', db_path, level=3)
    logger.info(f"Sistema retomado por user {user_id}")
    return {'ok': True, 'stopped': False}


def is_emergency_stopped():
    return _emergency_stop


def detect_emergency_stop(message):
    """Deteta frase de emergência numa mensagem."""
    return EMERGENCY_STOP_PHRASE.lower() in message.lower()


def verify_auth_phrase(message, action_type='execute'):
    """Verifica se a frase de autorização está presente."""
    required = AUTH_PHRASES.get(action_type, AUTH_PHRASES['execute'])
    return required in message


def classify_action_level(action_description):
    """
    Classifica o nível de risco de uma ação.
    Retorna: 1, 2, ou 3
    """
    desc = action_description.lower()
    
    # Nível 3 — ações financeiras reais
    level3_keywords = [
        'comprar', 'vender', 'investir', 'transferir', 'depositar', 'retirar',
        'ordem de compra', 'ordem de venda', 'trade', 'operação real',
        'xtb', 'broker', 'bolsa', 'ação', 'etf', 'cripto',
        'dinheiro real', 'conta real', 'mercado real'
    ]
    if any(k in desc for k in level3_keywords):
        return 3
    
    # Nível 2 — alterações internas
    level2_keywords = [
        'apagar', 'deletar', 'modificar configuração', 'alterar password',
        'mudar limite', 'atualizar perfil', 'reset', 'eliminar'
    ]
    if any(k in desc for k in level2_keywords):
        return 2
    
    # Nível 1 — análise e simulação
    return 1


def audit_log(user_id, action_type, description, db_path, level=1, result='ok', metadata=None):
    """Regista todas as ações sensíveis."""
    try:
        import sqlite3
        conn = get_db(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                action_type TEXT,
                description TEXT,
                level INTEGER,
                result TEXT,
                metadata TEXT,
                ip TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "INSERT INTO audit_log (user_id, action_type, description, level, result, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, action_type, description[:500], level, result, json.dumps(metadata or {}))
        )
        conn.commit()
        conn.close()
        logger.info(f"AUDIT L{level} [{action_type}] user={user_id}: {description[:80]}")
    except Exception as e:
        logger.error(f"Audit log error: {e}")


def get_audit_logs(user_id, db_path, limit=50):
    """Retorna logs de auditoria do utilizador."""
    try:
        import sqlite3
        conn = get_db(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def block_external_access(request_info, db_path, user_id=0):
    """Regista e bloqueia tentativas de acesso externo suspeito."""
    ip = request_info.get('ip', 'unknown')
    path = request_info.get('path', '')
    audit_log(user_id, 'BLOCKED_ACCESS', f"Tentativa bloqueada: {ip} → {path}",
              db_path, level=3, result='blocked')
    logger.warning(f"ACESSO BLOQUEADO: {ip} → {path}")


def check_action_allowed(action_description, session_data, message=''):
    """
    Verifica se uma ação é permitida com base no nível e autorizações.
    Retorna: {'allowed': bool, 'level': int, 'reason': str, 'needs': list}
    """
    if is_emergency_stopped():
        return {
            'allowed': False, 'level': 3,
            'reason': '🛑 TRAVÃO DE EMERGÊNCIA ATIVO. Sistema parado.',
            'needs': ['EMERGENCY_RESUME']
        }
    
    level = classify_action_level(action_description)
    
    if level == 1:
        return {'allowed': True, 'level': 1, 'reason': 'Análise/simulação permitida', 'needs': []}
    
    if level == 2:
        pin_verified = session_data.get('pin_verified', False)
        if pin_verified:
            return {'allowed': True, 'level': 2, 'reason': 'Ação interna autorizada', 'needs': []}
        return {
            'allowed': False, 'level': 2,
            'reason': 'Esta ação requer confirmação PIN',
            'needs': ['PIN']
        }
    
    if level == 3:
        needs = []
        pin_verified = session_data.get('pin_verified', False)
        webauthn_verified = session_data.get('webauthn_verified', False)
        phrase_ok = verify_auth_phrase(message)
        
        if not webauthn_verified: needs.append('WEBAUTHN')
        if not pin_verified: needs.append('PIN')
        if not phrase_ok: needs.append(f'FRASE: "{AUTH_PHRASES["execute"]}"')
        
        if needs:
            return {
                'allowed': False, 'level': 3,
                'reason': '⚠️ Ação financeira real — requer autorização máxima',
                'needs': needs
            }
        return {'allowed': True, 'level': 3, 'reason': 'Totalmente autorizado', 'needs': []}
    
    return {'allowed': False, 'level': 0, 'reason': 'Nível desconhecido', 'needs': []}
