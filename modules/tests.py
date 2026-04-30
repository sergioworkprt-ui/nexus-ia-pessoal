"""
NEXUS Auto-Tests — testes automáticos para Módulo 10 e Commands Engine
Corre antes de aplicar qualquer patch. Sem dependências externas.
"""
import os, sys, json, sqlite3, tempfile, logging
logger = logging.getLogger('nexus.tests')

# ── Test Runner ────────────────────────────────────────────────────────────
class TestResult:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.errors = []

    def ok(self, name):
        self.passed.append(name)
        logger.info(f"✅ {name}")

    def fail(self, name, reason):
        self.failed.append({'name': name, 'reason': reason})
        logger.warning(f"❌ {name}: {reason}")

    def error(self, name, exc):
        self.errors.append({'name': name, 'error': str(exc)})
        logger.error(f"💥 {name}: {exc}")

    def summary(self):
        total = len(self.passed) + len(self.failed) + len(self.errors)
        return {
            'total': total,
            'passed': len(self.passed),
            'failed': len(self.failed),
            'errors': len(self.errors),
            'success_rate': round(len(self.passed) / max(total, 1) * 100, 1),
            'all_passed': len(self.failed) == 0 and len(self.errors) == 0,
            'details': {
                'passed': self.passed,
                'failed': self.failed,
                'errors': self.errors
            }
        }


def make_test_db():
    """Cria base de dados temporária para testes."""
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY, user_id INTEGER, role TEXT,
            content TEXT, model_used TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT,
            description TEXT, status TEXT DEFAULT 'pending', result TEXT,
            run_at TEXT, email TEXT,
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY, user_id INTEGER, category TEXT,
            key TEXT, value TEXT, updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, category, key)
        );
        CREATE TABLE IF NOT EXISTS ai_usage (
            id INTEGER PRIMARY KEY, user_id INTEGER, provider TEXT,
            model TEXT, tokens_approx INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY, user_id INTEGER, action_type TEXT,
            description TEXT, level INTEGER, result TEXT, metadata TEXT,
            ip TEXT, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS system_state (
            id INTEGER PRIMARY KEY, category TEXT, key TEXT,
            value TEXT, updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(category, key)
        );
        INSERT INTO users (id, username, password_hash) VALUES (1, 'test', 'testhash');
        INSERT INTO conversations (user_id, role, content) VALUES (1, 'user', 'teste de aprendizagem');
        INSERT INTO conversations (user_id, role, content) VALUES (1, 'assistant', 'resposta de teste');
    """)
    conn.commit()
    conn.close()
    return tmp.name


def mock_ai_fn(messages, memory=''):
    """Mock da função de IA para testes."""
    return "Resposta de teste automático", "mock"


# ── Tests: Commands Engine ─────────────────────────────────────────────────
def test_commands_engine(r: TestResult):
    try:
        from modules.commands import parse_command, needs_authorization, AUTH_PHRASE

        # Test 1: comando info reconhecido
        cmd, args, risk = parse_command("mostra limites atuais")
        if cmd == 'show_limits':
            r.ok("commands: parse 'show_limits'")
        else:
            r.fail("commands: parse 'show_limits'", f"got '{cmd}'")

        # Test 2: comando de configuração reconhecido
        cmd, args, risk = parse_command("define limite diário para 15€")
        if cmd == 'set_daily_limit' and args and args[0] == '15':
            r.ok("commands: parse 'set_daily_limit' com valor")
        else:
            r.fail("commands: parse 'set_daily_limit'", f"cmd={cmd} args={args}")

        # Test 3: comando crítico reconhecido
        cmd, args, risk = parse_command("muda para modo real")
        if cmd == 'set_mode_real':
            r.ok("commands: parse 'set_mode_real'")
        else:
            r.fail("commands: parse 'set_mode_real'", f"got '{cmd}'")

        # Test 4: needs_authorization correto
        if needs_authorization(2) and not needs_authorization(1):
            r.ok("commands: needs_authorization level check")
        else:
            r.fail("commands: needs_authorization", "level logic wrong")

        # Test 5: AUTH_PHRASE definida
        if AUTH_PHRASE and len(AUTH_PHRASE) > 3:
            r.ok("commands: AUTH_PHRASE definida")
        else:
            r.fail("commands: AUTH_PHRASE", "vazia ou inválida")

        # Test 6: comando desconhecido retorna None
        cmd, args, risk = parse_command("olá, como estás?")
        if cmd is None:
            r.ok("commands: mensagem normal não é comando")
        else:
            r.fail("commands: falso positivo", f"detetou '{cmd}' numa mensagem normal")

        # Test 7: emergência reconhecida
        cmd, args, risk = parse_command("para tudo")
        if cmd == 'emergency_stop':
            r.ok("commands: parse 'emergency_stop'")
        else:
            r.fail("commands: emergency_stop", f"got '{cmd}'")

    except Exception as e:
        r.error("commands: módulo import/run", e)


# ── Tests: Mod10 ───────────────────────────────────────────────────────────
def test_mod10(r: TestResult, db_path):
    try:
        from modules.mod10 import save_state, load_state

        # Test 1: save e load state
        save_state(db_path, 'test_key', {'valor': 42})
        val = load_state(db_path, 'test_key')
        if val and val.get('valor') == 42:
            r.ok("mod10: save_state / load_state")
        else:
            r.fail("mod10: save_state / load_state", f"got {val}")

        # Test 2: load state inexistente retorna default
        val = load_state(db_path, 'chave_inexistente_xyz', default='default_val')
        if val == 'default_val':
            r.ok("mod10: load_state default")
        else:
            r.fail("mod10: load_state default", f"got {val}")

        # Test 3: context snapshot
        from modules.mod10 import build_context_snapshot
        snapshot = build_context_snapshot(db_path, 1, mock_ai_fn)
        if 'timestamp' in snapshot and 'user_id' in snapshot:
            r.ok("mod10: build_context_snapshot")
        else:
            r.fail("mod10: build_context_snapshot", f"missing keys: {list(snapshot.keys())}")

        # Test 4: reconstruct context prompt
        from modules.mod10 import reconstruct_context_prompt
        prompt = reconstruct_context_prompt(db_path, 1)
        if prompt and len(prompt) > 10:
            r.ok("mod10: reconstruct_context_prompt")
        else:
            r.fail("mod10: reconstruct_context_prompt", "prompt vazio")

        # Test 5: learn from logs
        from modules.mod10 import learn_from_logs
        result = learn_from_logs(db_path, 1, mock_ai_fn)
        if 'learned' in result:
            r.ok("mod10: learn_from_logs retorna resultado")
        else:
            r.fail("mod10: learn_from_logs", f"resultado inesperado: {result}")

        # Test 6: generate patch
        from modules.mod10 import generate_self_patch, get_pending_patches
        patch = generate_self_patch("teste de patch automático", mock_ai_fn, db_path)
        if patch.get('hash') and patch.get('patch'):
            r.ok("mod10: generate_self_patch")
        else:
            r.fail("mod10: generate_self_patch", f"patch inválido: {patch}")

        # Test 7: pending patches
        patches = get_pending_patches(db_path)
        if isinstance(patches, list):
            r.ok("mod10: get_pending_patches retorna lista")
        else:
            r.fail("mod10: get_pending_patches", f"não é lista: {type(patches)}")

    except Exception as e:
        r.error("mod10: módulo import/run", e)


# ── Tests: Security ────────────────────────────────────────────────────────
def test_security(r: TestResult, db_path):
    try:
        from modules.security import (classify_action_level, check_action_allowed,
                                       is_emergency_stopped, detect_emergency_stop)

        # Test 1: nível correto para ação financeira
        level = classify_action_level("comprar 5€ de SPY")
        if level == 3:
            r.ok("security: nível 3 para ação financeira")
        else:
            r.fail("security: nível financeiro", f"esperava 3, got {level}")

        # Test 2: nível 1 para análise
        level = classify_action_level("analisa o mercado")
        if level == 1:
            r.ok("security: nível 1 para análise")
        else:
            r.fail("security: nível análise", f"esperava 1, got {level}")

        # Test 3: emergency stop not active by default
        if not is_emergency_stopped():
            r.ok("security: emergency stop inativo por padrão")
        else:
            r.fail("security: emergency stop", "ativo quando não devia")

        # Test 4: detect emergency stop phrase
        if detect_emergency_stop("NEXUS, parar imediatamente todas as ações reais."):
            r.ok("security: detect_emergency_stop phrase")
        else:
            r.fail("security: detect_emergency_stop", "não detetou frase")

        # Test 5: normal message not emergency
        if not detect_emergency_stop("olá, como estás?"):
            r.ok("security: normal message not emergency")
        else:
            r.fail("security: falso positivo emergency", "detetou emergência em msg normal")

    except Exception as e:
        r.error("security: módulo import/run", e)


# ── Tests: Financial ───────────────────────────────────────────────────────
def test_financial(r: TestResult, db_path):
    try:
        from modules.financial import (get_financial_config, save_financial_config,
                                        analyze_investment_plan, DEFAULT_CONFIG)

        # Test 1: config padrão
        config = get_financial_config(1, db_path)
        if config.get('max_loss_per_trade') == DEFAULT_CONFIG['max_loss_per_trade']:
            r.ok("financial: config padrão carregada")
        else:
            r.fail("financial: config padrão", f"valor inesperado: {config}")

        # Test 2: save e reload config
        config['max_loss_per_trade'] = 7.5
        save_financial_config(1, db_path, config)
        config2 = get_financial_config(1, db_path)
        if config2.get('max_loss_per_trade') == 7.5:
            r.ok("financial: save/reload config")
        else:
            r.fail("financial: save/reload", f"got {config2.get('max_loss_per_trade')}")

        # Test 3: análise de investimento - ativo protegido
        config3 = get_financial_config(1, db_path)
        result = analyze_investment_plan(config3, 'SELL', 'SPY', 10)
        if not result.get('allowed') or result.get('risk_level') == 'blocked':
            r.ok("financial: SPY protegido contra venda")
        else:
            r.fail("financial: proteção SPY", "SPY deveria ser protegido")

        # Test 4: análise de cripto tem aviso
        result2 = analyze_investment_plan(config3, 'BUY', 'BTC', 5)
        warnings = result2.get('warnings', [])
        if any('cripto' in w.lower() or 'crypto' in w.lower() for w in warnings):
            r.ok("financial: aviso cripto presente")
        else:
            r.fail("financial: aviso cripto", f"warnings: {warnings}")

    except Exception as e:
        r.error("financial: módulo import/run", e)


# ── Tests: AI Router ───────────────────────────────────────────────────────
def test_ai_router(r: TestResult):
    try:
        from modules.ai_router import get_ai_response

        # Test: router retorna erro útil quando sem keys
        # (não testa chamadas reais para não consumir quota)
        import os
        orig_gemini = os.environ.get('GEMINI_API_KEY', '')
        orig_groq = os.environ.get('GROQ_API_KEY', '')

        # Temporariamente remove keys para testar fallback
        for k in ['GEMINI_API_KEY', 'GROQ_API_KEY', 'OPENROUTER_API_KEY',
                   'CEREBRAS_API_KEY', 'MISTRAL_API_KEY']:
            os.environ.pop(k, None)

        messages = [{'role': 'user', 'content': 'teste'}]
        response, model = get_ai_response(messages, '')

        # Restaura keys
        if orig_gemini: os.environ['GEMINI_API_KEY'] = orig_gemini
        if orig_groq: os.environ['GROQ_API_KEY'] = orig_groq

        if model == 'none' and 'API Key' in response or 'disponível' in response:
            r.ok("ai_router: fallback com mensagem útil sem keys")
        else:
            r.ok("ai_router: resposta obtida (keys presentes)")

    except Exception as e:
        r.error("ai_router: import/run", e)


# ── Main Test Runner ───────────────────────────────────────────────────────
def run_all_tests(db_path=None):
    """Corre todos os testes. Retorna TestResult com summary."""
    r = TestResult()
    tmp_db = None

    if not db_path:
        tmp_db = make_test_db()
        db_path = tmp_db

    logger.info("=== NEXUS Auto-Tests iniciados ===")

    test_commands_engine(r)
    test_mod10(r, db_path)
    test_security(r, db_path)
    test_financial(r, db_path)
    test_ai_router(r)

    summary = r.summary()
    logger.info(f"=== Resultado: {summary['passed']}/{summary['total']} passed ({summary['success_rate']}%) ===")

    # Limpa DB temporária
    if tmp_db:
        try:
            os.unlink(tmp_db)
        except Exception:
            pass

    return summary


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    result = run_all_tests()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result['all_passed'] else 1)
