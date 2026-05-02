from modules.database import get_db
"""
NEXUS Módulo 10 — Automação Total e Auto-Evolução
- Scheduler interno com continuidade
- Auto-evolução do código
- Aprendizagem contínua
- Reconstrução de contexto
- Execução autónoma dentro de limites
"""
import os, json, threading, time, datetime, logging, sqlite3, hashlib
logger = logging.getLogger('nexus.mod10')

_mod10_running = False
_mod10_thread = None
_mod10_state = {}


# ── Estado e Contexto ─────────────────────────────────────────────────────
def save_state(db_path, key, value, category='mod10'):
    """Guarda estado persistente — usa tabela dedicada para evitar conflitos."""
    try:
        conn = get_db(db_path)
        # Usa tabela própria para estado do sistema
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_state (
                id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(category, key)
            )
        """)
        val = json.dumps(value) if not isinstance(value, str) else value
        conn.execute("""
            INSERT INTO system_state (category, key, value, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(category, key)
            DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (category, key, val))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"save_state error: {e}")


def load_state(db_path, key, category='mod10', default=None):
    """Carrega estado persistente da tabela system_state."""
    try:
        conn = get_db(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_state (
                id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(category, key)
            )
        """)
        row = conn.execute(
            "SELECT value FROM system_state WHERE category=? AND key=?",
            (category, key)
        ).fetchone()
        conn.close()
        if row:
            try:
                return json.loads(row['value'])
            except Exception:
                return row['value']
    except Exception as e:
        logger.debug(f"load_state error: {e}")
    return default


def build_context_snapshot(db_path, user_id, ai_fn=None):
    """
    Constrói snapshot completo do contexto para reconstrução.
    Útil para continuar projetos após reset ou nova sessão.
    """
    try:
        conn = get_db(db_path)
        conn.row_factory = sqlite3.Row

        # Últimas conversas
        convs = conn.execute(
            "SELECT role, content, created_at FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 20",
            (user_id,)
        ).fetchall()

        # Memória
        mems = conn.execute(
            "SELECT category, key, value FROM memory WHERE user_id=?", (user_id,)
        ).fetchall()

        # Tarefas
        tasks = conn.execute(
            "SELECT title, status, result FROM tasks WHERE user_id=? ORDER BY id DESC LIMIT 10",
            (user_id,)
        ).fetchall()

        # Logs de auditoria recentes
        try:
            audits = conn.execute(
                "SELECT action_type, description, level, created_at FROM audit_log WHERE user_id=? ORDER BY id DESC LIMIT 10",
                (user_id,)
            ).fetchall()
        except Exception:
            audits = []

        # Alertas recentes
        try:
            alerts = conn.execute(
                "SELECT symbol, alert_type, change_pct, created_at FROM market_alerts WHERE user_id=? ORDER BY id DESC LIMIT 5",
                (user_id,)
            ).fetchall()
        except Exception:
            alerts = []

        conn.close()

        snapshot = {
            'timestamp': datetime.datetime.now().isoformat(),
            'user_id': user_id,
            'conversations': [dict(c) for c in reversed(convs)],
            'memory': {f"{m['category']}/{m['key']}": m['value'] for m in mems},
            'tasks': [dict(t) for t in tasks],
            'audit': [dict(a) for a in audits],
            'alerts': [dict(a) for a in alerts],
        }

        save_state(db_path, f'context_snapshot_{user_id}', snapshot)
        logger.info(f"Context snapshot guardado para user {user_id}")
        return snapshot

    except Exception as e:
        logger.error(f"build_context_snapshot error: {e}")
        return {}


def reconstruct_context_prompt(db_path, user_id):
    """Gera prompt para reconstruir contexto numa nova sessão."""
    snapshot = load_state(db_path, f'context_snapshot_{user_id}', default={})
    if not snapshot:
        return "Sem contexto guardado. Começa uma nova sessão."

    mem_text = '\n'.join([f"  {k}: {v}" for k, v in list(snapshot.get('memory', {}).items())[:10]])
    task_text = '\n'.join([f"  [{t['status']}] {t['title']}" for t in snapshot.get('tasks', [])[:5]])
    conv_text = '\n'.join([f"  {c['role']}: {c['content'][:80]}" for c in snapshot.get('conversations', [])[-5:]])

    return f"""=== CONTEXTO DA NEXUS (reconstruído em {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}) ===

MEMÓRIA DO UTILIZADOR:
{mem_text or '  (sem memória)'}

TAREFAS RECENTES:
{task_text or '  (sem tarefas)'}

ÚLTIMAS CONVERSAS:
{conv_text or '  (sem conversas)'}

SNAPSHOT: {snapshot.get('timestamp', 'desconhecido')}
=== FIM DO CONTEXTO ==="""


# ── Aprendizagem Contínua ─────────────────────────────────────────────────
def learn_from_logs(db_path, user_id, ai_fn):
    """Aprende com logs de auditoria, erros e operações."""
    try:
        conn = get_db(db_path)
        conn.row_factory = sqlite3.Row

        # Erros recentes
        try:
            errors = conn.execute(
                "SELECT action_type, description, result FROM audit_log WHERE user_id=? AND result='error' ORDER BY id DESC LIMIT 20",
                (user_id,)
            ).fetchall()
        except Exception:
            errors = []

        # Operações XTB
        try:
            ops = conn.execute(
                "SELECT cmd, symbol, amount_eur, mode, error FROM xtb_orders WHERE user_id=? ORDER BY id DESC LIMIT 10",
                (user_id,)
            ).fetchall()
        except Exception:
            ops = []

        conn.close()

        if not errors and not ops:
            return {'learned': False, 'reason': 'Sem dados suficientes'}

        errors_text = '\n'.join([f"  [{e['action_type']}] {e['description'][:80]}" for e in errors])
        ops_text = '\n'.join([f"  {o['cmd']} {o['symbol']} {o['amount_eur']}€ [{o['mode']}] {'✅' if not o['error'] else '❌ '+str(o['error'])[:50]}" for o in ops])

        prompt = f"""Analisa estes dados de operação da NEXUS e extrai aprendizagens:

ERROS RECENTES:
{errors_text or '  Nenhum erro recente ✅'}

OPERAÇÕES XTB:
{ops_text or '  Sem operações ainda'}

Com base nisto:
1. O que está a funcionar bem?
2. O que está a falhar e porquê?
3. Que padrões identificas?
4. Que ajustes recomendas (limites, estratégia, configuração)?
5. Prioridade: o que corrigir PRIMEIRO?

Sê conciso e orientado a ação."""

        messages = [{'role': 'user', 'content': prompt}]
        response, model = ai_fn(messages, '')

        # Guarda aprendizagem
        insight = {
            'timestamp': datetime.datetime.now().isoformat(),
            'errors_analyzed': len(errors),
            'ops_analyzed': len(ops),
            'insight': response,
            'model': model
        }
        save_state(db_path, 'latest_learning', insight)
        logger.info(f"Aprendizagem guardada [{model}]")
        return {'learned': True, 'insight': response, 'model': model}

    except Exception as e:
        logger.error(f"learn_from_logs error: {e}")
        return {'learned': False, 'error': str(e)}


# ── Auto-Evolução ─────────────────────────────────────────────────────────
def analyze_codebase_health(ai_fn):
    """Analisa saúde do codebase e sugere melhorias."""
    modules_dir = os.path.join(os.path.dirname(__file__))
    module_summaries = []

    for fname in sorted(os.listdir(modules_dir)):
        if fname.endswith('.py') and not fname.startswith('_'):
            fpath = os.path.join(modules_dir, fname)
            try:
                with open(fpath, 'r') as f:
                    content = f.read()
                lines = len(content.split('\n'))
                has_error_handling = 'except' in content
                has_logging = 'logger' in content
                has_tests = 'def test_' in content
                module_summaries.append(
                    f"  {fname}: {lines} linhas | "
                    f"{'✅ erros' if has_error_handling else '❌ sem error handling'} | "
                    f"{'✅ logs' if has_logging else '❌ sem logs'} | "
                    f"{'✅ testes' if has_tests else '❌ sem testes'}"
                )
            except Exception:
                pass

    prompt = f"""Analisa a saúde do codebase da NEXUS:

MÓDULOS:
{chr(10).join(module_summaries)}

Identifica:
1. Módulos mais críticos que precisam de melhoria
2. Padrões de código problemáticos
3. Funcionalidades em falta mais importantes
4. Sugestões de refactoring prioritárias
5. Um patch concreto (código Python) para a melhoria mais importante

Mantém a resposta prática e implementável."""

    messages = [{'role': 'user', 'content': prompt}]
    response, model = ai_fn(messages, '')
    return {'analysis': response, 'model': model, 'modules_analyzed': len(module_summaries)}


def generate_self_patch(issue_description, ai_fn, db_path):
    """Gera patch para um problema identificado."""
    prompt = f"""Gera um patch Python para corrigir este problema na NEXUS:

PROBLEMA: {issue_description}

REGRAS:
- Código Python válido e seguro
- Sem hardcode de credenciais
- Com logging adequado
- Com tratamento de erros
- Compatível com Flask + SQLite

Responde com:
1. FICHEIRO a modificar
2. FUNÇÃO a alterar/criar
3. CÓDIGO COMPLETO do patch
4. COMO TESTAR"""

    messages = [{'role': 'user', 'content': prompt}]
    response, model = ai_fn(messages, '')

    patch = {
        'timestamp': datetime.datetime.now().isoformat(),
        'issue': issue_description,
        'patch': response,
        'model': model,
        'status': 'pending_review',
        'hash': hashlib.md5(response.encode()).hexdigest()[:8]
    }

    # Guarda patch para revisão
    patches = load_state(db_path, 'pending_patches', default=[])
    patches.append(patch)
    patches = patches[-10:]  # máximo 10 patches pendentes
    save_state(db_path, 'pending_patches', patches)

    logger.info(f"Patch gerado: {patch['hash']} para: {issue_description[:50]}")
    return patch


def get_pending_patches(db_path):
    """Retorna patches pendentes de revisão."""
    return load_state(db_path, 'pending_patches', default=[])


def approve_patch(db_path, patch_hash, approved_by):
    """Marca patch como aprovado (ainda não aplica — requer deploy manual)."""
    patches = load_state(db_path, 'pending_patches', default=[])
    for p in patches:
        if p.get('hash') == patch_hash:
            p['status'] = 'approved'
            p['approved_by'] = approved_by
            p['approved_at'] = datetime.datetime.now().isoformat()
    save_state(db_path, 'pending_patches', patches)
    return True


# ── Scheduler Interno ─────────────────────────────────────────────────────

# ── Rollback System ───────────────────────────────────────────────────────
def backup_module(module_path):
    """Faz backup de um módulo antes de aplicar patch."""
    import shutil
    backup_path = module_path + '.bak'
    try:
        shutil.copy2(module_path, backup_path)
        logger.info(f"Backup criado: {backup_path}")
        return backup_path, None
    except Exception as e:
        return None, str(e)


def rollback_module(backup_path, original_path):
    """Restaura módulo de backup após falha."""
    import shutil
    try:
        shutil.copy2(backup_path, original_path)
        logger.info(f"Rollback executado: {original_path}")
        return True, None
    except Exception as e:
        return False, str(e)


def apply_patch_safe(patch_content, target_file, db_path, run_tests=True):
    """
    Aplica patch com backup automático e rollback se falhar.
    1. Backup do ficheiro atual
    2. Aplica patch
    3. Verifica sintaxe Python
    4. Corre testes automáticos
    5. Se falhar → rollback automático
    """
    import py_compile, tempfile, shutil

    result = {
        'success': False,
        'backup_path': None,
        'error': None,
        'rolled_back': False,
        'tests': None
    }

    # 1. Backup
    backup_path, err = backup_module(target_file)
    if err:
        result['error'] = f"Backup falhou: {err}"
        return result
    result['backup_path'] = backup_path

    try:
        # 2. Escreve patch
        with open(target_file, 'w') as f:
            f.write(patch_content)
        logger.info(f"Patch aplicado em: {target_file}")

        # 3. Verifica sintaxe
        try:
            py_compile.compile(target_file, doraise=True)
            logger.info("Sintaxe Python OK")
        except py_compile.PyCompileError as e:
            raise Exception(f"Erro de sintaxe: {e}")

        # 4. Testes automáticos
        if run_tests:
            from modules.tests import run_all_tests
            test_result = run_all_tests(db_path)
            result['tests'] = test_result
            if not test_result['all_passed']:
                raise Exception(
                    f"Testes falharam: {test_result['failed']} falhas, "
                    f"{test_result['errors']} erros"
                )
            logger.info(f"Testes passaram: {test_result['passed']}/{test_result['total']}")

        result['success'] = True
        # Remove backup após sucesso
        try:
            os.remove(backup_path)
        except Exception:
            pass
        logger.info(f"Patch aplicado com sucesso em: {target_file}")

    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Patch falhou: {e} — a fazer rollback...")

        # 5. Rollback automático
        ok, rb_err = rollback_module(backup_path, target_file)
        result['rolled_back'] = ok
        if ok:
            logger.info("Rollback concluído com sucesso")
        else:
            logger.error(f"Rollback FALHOU: {rb_err}")

    return result


class Mod10Scheduler:
    """Scheduler do Módulo 10 — executa tarefas automáticas."""

    def __init__(self):
        self._running = False
        self._thread = None
        self._db_path = None
        self._ai_fn = None
        self._send_email = None
        self._tasks = []

    def start(self, db_path, ai_fn, send_email_fn):
        self._db_path = db_path
        self._ai_fn = ai_fn
        self._send_email = send_email_fn
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Módulo 10 Scheduler iniciado")

    def _loop(self):
        cycle = 0
        while self._running:
            try:
                cycle += 1
                now = datetime.datetime.now()
                logger.info(f"Mod10 ciclo {cycle} — {now.strftime('%H:%M')}")

                # A cada ciclo (30 min): snapshot de contexto
                self._run_context_snapshot()

                # A cada 2 horas: aprendizagem
                if cycle % 4 == 0:
                    self._run_learning()

                # A cada 6 horas: análise de saúde do código
                if cycle % 12 == 0:
                    self._run_health_check()

                # A cada 24 horas: relatório completo
                if now.hour == 8 and now.minute < 30:
                    self._run_daily_report()

                # Tarefas agendadas pelo utilizador
                self._run_user_tasks()

                save_state(self._db_path, 'last_cycle', {
                    'cycle': cycle,
                    'timestamp': now.isoformat(),
                    'running': True
                })

            except Exception as e:
                logger.error(f"Mod10 loop error: {e}")

            time.sleep(30 * 60)  # 30 minutos

    def _run_context_snapshot(self):
        """Guarda snapshot de contexto."""
        try:
            import sqlite3
            conn = get_db(self._db_path)
            users = conn.execute("SELECT DISTINCT user_id FROM conversations").fetchall()
            conn.close()
            for (uid,) in users:
                build_context_snapshot(self._db_path, uid, self._ai_fn)
        except Exception as e:
            logger.error(f"Context snapshot error: {e}")

    def _run_learning(self):
        """Executa ciclo de aprendizagem."""
        try:
            import sqlite3
            conn = get_db(self._db_path)
            users = conn.execute("SELECT DISTINCT user_id FROM conversations").fetchall()
            conn.close()
            for (uid,) in users:
                result = learn_from_logs(self._db_path, uid, self._ai_fn)
                if result.get('learned') and self._send_email:
                    email = os.environ.get('GMAIL_ADDRESS', '')
                    if email:
                        try:
                            self._send_email(
                                email,
                                "🧠 NEXUS — Aprendizagem Concluída",
                                f"A NEXUS aprendeu com os teus dados:\n\n{result.get('insight', '')}"
                            )
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Learning cycle error: {e}")

    def _run_health_check(self):
        """Analisa saúde do código."""
        try:
            result = analyze_codebase_health(self._ai_fn)
            save_state(self._db_path, 'latest_health_check', result)
            logger.info("Health check concluído")
        except Exception as e:
            logger.error(f"Health check error: {e}")

    def _run_daily_report(self):
        """Gera e envia relatório diário."""
        try:
            email = os.environ.get('GMAIL_ADDRESS', '')
            if not email or not self._send_email:
                return
            # Resumo do dia
            state = load_state(self._db_path, 'last_cycle', default={})
            learning = load_state(self._db_path, 'latest_learning', default={})
            report = f"""📊 NEXUS — Relatório Diário {datetime.datetime.now().strftime('%d/%m/%Y')}

ESTADO DO SISTEMA:
• Ciclos executados: {state.get('cycle', 0)}
• Último ciclo: {state.get('timestamp', 'N/A')}

APRENDIZAGEM RECENTE:
{learning.get('insight', 'Sem dados')[:500]}

A NEXUS está a funcionar 24/7.
Acede em: https://nexus-ia-pessoal.onrender.com"""
            self._send_email(email, "📊 NEXUS — Relatório Diário", report)
            logger.info("Relatório diário enviado")
        except Exception as e:
            logger.error(f"Daily report error: {e}")

    def _run_user_tasks(self):
        """Executa tarefas agendadas pelo utilizador (scheduler existente)."""
        # O scheduler principal já faz isto — sem duplicação
        pass

    def is_running(self):
        return self._running and self._thread and self._thread.is_alive()

    def get_status(self, db_path=None):
        state = load_state(db_path or self._db_path, 'last_cycle', default={})
        patches = get_pending_patches(db_path or self._db_path)
        learning = load_state(db_path or self._db_path, 'latest_learning', default={})
        return {
            'running': self.is_running(),
            'last_cycle': state.get('timestamp', 'nunca'),
            'cycles_total': state.get('cycle', 0),
            'pending_patches': len(patches),
            'last_learning': learning.get('timestamp', 'nunca'),
        }

    def stop(self):
        self._running = False


mod10 = Mod10Scheduler()
