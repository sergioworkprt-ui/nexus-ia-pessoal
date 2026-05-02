"""
NEXUS IA Pessoal — Versão Pro
Servidor principal Flask com suporte a modo Free e Pago
"""
import os, sys, json, hashlib, secrets, sqlite3, datetime, logging
import urllib.request, urllib.error
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory

# ── Detectar modo (Free vs Pago) ──────────────────────────────────────────
DATA_DIR = '/data' if os.path.exists('/data') and os.access('/data', os.W_OK) else 'data'
IS_PAID = DATA_DIR == '/data'

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(f'{DATA_DIR}/logs', exist_ok=True)
os.makedirs(f'{DATA_DIR}/tasks', exist_ok=True)
os.makedirs(f'{DATA_DIR}/uploads', exist_ok=True)
os.makedirs(f'{DATA_DIR}/reports', exist_ok=True)

DB_PATH = f'{DATA_DIR}/nexus.db'

# ── Logging ───────────────────────────────────────────────────────────────
log_file = f'{DATA_DIR}/logs/nexus.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('nexus')

# ── Flask App ─────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', 'nexus-default-key-change-this')
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB uploads
# Desativa cache do Flask para ficheiros estáticos (por defeito é 12h)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def set_cache_headers(response):
    path = request.path
    # HTML, raiz e API: nunca cachear
    if (path == '/' or path.endswith('.html') or
            path.startswith('/api/') or path.endswith('sw.js')):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma']  = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# ── Import modules ────────────────────────────────────────────────────────
from modules.database import init_db, get_db, ensure_healthy, check_integrity, repair_db, safe_close
from modules.ai_router import get_ai_response, get_router_status, reload_and_validate
from modules.email_sender import send_email
from modules.youtube import get_youtube_transcript
from modules.scheduler import scheduler
from modules.notifications import notify
from modules.security import (audit_log, check_action_allowed, detect_emergency_stop,
    emergency_stop as sec_emergency_stop, emergency_resume as sec_emergency_resume,
    get_audit_logs, classify_action_level, is_emergency_stopped)
from modules.financial import (get_financial_config, save_financial_config,
    log_operation, get_portfolio_summary, analyze_investment_plan, fact_check_investment_claim)
from modules.learning import (analyze_conversation_patterns, compare_sources,
    generate_improvement_plan, investment_education, get_learning_history)
from modules.xtb import (xtb_login, get_account_info, get_positions, place_order,
    close_position, get_symbol_price, get_xtb_orders_history)
from modules.market_monitor import (market_monitor, get_monitor_config, save_monitor_config,
    load_watched_assets, save_watched_assets, get_recent_alerts, get_asset_price,
    check_all_assets, MODE_ASK, MODE_AUTO)
from modules.sms import send_sms
from modules.evolution import (generate_code, analyze_and_fix, suggest_improvements,
    list_modules, read_module, generate_new_module, create_update_zip)
from modules.commands import (parse_command, needs_authorization, check_authorization,
    format_command_response, execute_command, AUTH_PHRASE)
from modules.mod10 import (mod10, build_context_snapshot, reconstruct_context_prompt,
    learn_from_logs, analyze_codebase_health, generate_self_patch,
    get_pending_patches, approve_patch, load_state, save_state)
from modules.learning import (analyze_conversation_patterns, compare_sources,
    generate_improvement_plan, investment_education, get_learning_history)

# ── Arranque: verifica saúde da DB antes de tudo ─────────────────────────
_db_health_ok, _db_health_msg = ensure_healthy(DB_PATH)
if not _db_health_ok:
    logger.error(f"DB health check FALHOU: {_db_health_msg} — a forçar reinicialização")
    repair_db(DB_PATH)

init_db(DB_PATH)

_db_health_ok, _db_health_msg = check_integrity(DB_PATH)
logger.info(f"DB integrity: {_db_health_msg} | path: {DB_PATH}")

scheduler.start(DB_PATH, get_ai_response, send_email)
market_monitor.start(DB_PATH, send_email, get_ai_response)
logger.info("Market Monitor iniciado")
mod10.start(DB_PATH, get_ai_response, send_email)
logger.info("Módulo 10 iniciado")

logger.info(f"NEXUS iniciada — Modo: {'PAGO (24/7)' if IS_PAID else 'FREE'} | DB: {DB_PATH}")

# ── Auth ──────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Não autenticado'}), 401
        return f(*args, **kwargs)
    return decorated

# ── Auth endpoints ────────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    pw_hash = hashlib.sha256(data.get('password', '').encode()).hexdigest()
    db = get_db(DB_PATH)
    user = db.execute("SELECT * FROM users WHERE username=? AND password_hash=?",
                      (data.get('username', '').strip(), pw_hash)).fetchone()
    db.close()
    if user:
        session.permanent = True
        session['user_id'] = user['id']
        session['username'] = user['username']
        logger.info(f"Login: {user['username']}")
        return jsonify({'ok': True, 'username': user['username'], 'mode': 'paid' if IS_PAID else 'free'})
    return jsonify({'error': 'Credenciais inválidas'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/me')
@login_required
def me():
    return jsonify({
        'username': session['username'],
        'user_id': session['user_id'],
        'mode': 'paid' if IS_PAID else 'free',
        'data_dir': DATA_DIR,
        'features': {
            'persistent_db': IS_PAID,
            'scheduler_24h': IS_PAID,
            'large_uploads': IS_PAID,
            'whisper': IS_PAID,
        }
    })

# ── Chat ──────────────────────────────────────────────────────────────────
@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    try:
        return _chat_inner()
    except Exception as e:
        logger.exception(f"Chat unhandled exception: {e}")
        return jsonify({
            'response': f'⚠️ Erro interno do servidor: {str(e)[:200]}\n\nTenta novamente ou usa `recarregar ia`.',
            'model': 'error'
        }), 200

def _chat_inner():
    from modules.enricher import detect_and_enrich
    data = request.json or {}
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'error': 'Mensagem vazia'}), 400

    user_id = session['user_id']

    # Detecta travão de emergência
    if detect_emergency_stop(user_message):
        sec_emergency_stop(user_id, DB_PATH)
        return jsonify({
            'response': '🛑 **TRAVÃO DE EMERGÊNCIA ATIVADO.**\n\nTodas as ações reais foram paradas imediatamente.\nO sistema continua a funcionar em modo de análise apenas.\n\nPara retomar, diz: "NEXUS, retomar operações."',
            'model': 'security', 'emergency': True
        })

    # Detecta retoma
    if 'nexus, retomar operações' in user_message.lower() and is_emergency_stopped():
        sec_emergency_resume(user_id, DB_PATH)

    db = get_db(DB_PATH)
    db.execute("INSERT INTO conversations (user_id, role, content) VALUES (?, 'user', ?)",
               (user_id, user_message))
    db.commit()
    history = db.execute(
        "SELECT role, content FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 20",
        (user_id,)
    ).fetchall()
    db.close()

    messages = [{'role': r['role'], 'content': r['content']} for r in reversed(history)]
    if not messages:
        messages = [{'role': 'user', 'content': user_message}]

    # ── CHAT COMMANDS ENGINE ──────────────────────────────────────────────
    try:
        pending = session.get('pending_command')
        if pending and AUTH_PHRASE.upper() in user_message.upper():
            cmd_response = execute_command(
                pending['command'], pending['args'], user_id, DB_PATH,
                dict(session), get_ai_response, send_email
            )
            session.pop('pending_command', None)
            audit_log(user_id, 'CMD_EXECUTED', pending['command'], DB_PATH,
                      level=pending['risk'], result='ok')
            ai_response = "✅ **Autorizado e executado:**\n\n" + str(cmd_response)
            model_used = 'commands'
        elif pending and 'NÃO' in user_message.upper():
            session.pop('pending_command', None)
            ai_response = "❌ Comando cancelado."
            model_used = 'commands'
        else:
            command, args, risk = parse_command(user_message)
            if command and risk == 1:
                ai_response = execute_command(
                    command, args, user_id, DB_PATH,
                    dict(session), get_ai_response, send_email
                )
                model_used = 'commands'
            elif command and needs_authorization(risk):
                session['pending_command'] = {'command': command, 'args': args, 'risk': risk}
                ai_response = format_command_response(command, args, risk, True)
                model_used = 'commands'
            else:
                extra = detect_and_enrich(user_message, DB_PATH, user_id)
                if extra and messages:
                    messages[-1]['content'] += extra

                db = get_db(DB_PATH)
                memories = db.execute(
                    "SELECT category, key, value FROM memory WHERE user_id=?", (user_id,)
                ).fetchall()
                db.close()

                memory_ctx = ""
                if memories:
                    memory_ctx = "\n\nMEMÓRIA DO UTILIZADOR:\n"
                    for m in memories:
                        memory_ctx += f"  [{m['category']}] {m['key']}: {m['value']}\n"

                ai_response, model_used = get_ai_response(messages, memory_ctx)

    except Exception as e:
        logger.error(f"Chat handler error: {e}", exc_info=True)
        return jsonify({'response': f'⚠️ Erro interno: {str(e)[:200]}', 'model': 'error'}), 200

    try:
        db = get_db(DB_PATH)
        db.execute(
            "INSERT INTO conversations (user_id, role, content, model_used) VALUES (?, 'assistant', ?, ?)",
            (user_id, ai_response, model_used)
        )
        db.commit()
        db.close()
    except Exception as e:
        logger.error(f"Chat save error: {e}")

    logger.info(f"Chat [{model_used}] user={user_id} chars={len(ai_response)}")

    if model_used != 'commands':
        email_triggers = ['envia email', 'manda email', 'notifica', 'avisa-me', 'envia-me']
        if any(t in user_message.lower() for t in email_triggers):
            gmail = os.environ.get('GMAIL_ADDRESS', '')
            if gmail:
                try:
                    send_email(gmail, "✅ NEXUS — Análise Concluída", ai_response)
                    ai_response += f"\n\n📧 Email enviado para {gmail}"
                except Exception as e:
                    logger.error(f"Email error: {e}")

    return jsonify({'response': ai_response, 'model': model_used})

@app.route('/api/history')
@login_required
def history():
    db = get_db(DB_PATH)
    rows = db.execute(
        "SELECT role, content, model_used, created_at FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 60",
        (session['user_id'],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in reversed(rows)])

@app.route('/api/clear-history', methods=['POST'])
@login_required
def clear_history():
    db = get_db(DB_PATH)
    db.execute("DELETE FROM conversations WHERE user_id=?", (session['user_id'],))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Memory ────────────────────────────────────────────────────────────────
@app.route('/api/memory', methods=['GET'])
@login_required
def get_memory():
    db = get_db(DB_PATH)
    rows = db.execute("SELECT * FROM memory WHERE user_id=? ORDER BY category, key",
                      (session['user_id'],)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/memory', methods=['POST'])
@login_required
def set_memory():
    data = request.json or {}
    db = get_db(DB_PATH)
    db.execute(
        """INSERT INTO memory (user_id, category, key, value, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(user_id, category, key)
           DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (session['user_id'], data.get('category', 'geral'), data.get('key'), data.get('value'))
    )
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/memory/<int:mem_id>', methods=['DELETE'])
@login_required
def delete_memory(mem_id):
    db = get_db(DB_PATH)
    db.execute("DELETE FROM memory WHERE id=? AND user_id=?", (mem_id, session['user_id']))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Tasks ─────────────────────────────────────────────────────────────────
@app.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    db = get_db(DB_PATH)
    rows = db.execute("SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC",
                      (session['user_id'],)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/tasks', methods=['POST'])
@login_required
def create_task():
    data = request.json or {}
    db = get_db(DB_PATH)
    db.execute(
        "INSERT INTO tasks (user_id, title, description, status) VALUES (?, ?, ?, ?)",
        (session['user_id'], data.get('title'), data.get('description', ''),
         data.get('status', 'pending'))
    )
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/tasks/<int:task_id>', methods=['PATCH'])
@login_required
def update_task(task_id):
    data = request.json or {}
    db = get_db(DB_PATH)
    db.execute(
        "UPDATE tasks SET status=?, result=?, updated_at=datetime('now') WHERE id=? AND user_id=?",
        (data.get('status'), data.get('result', ''), task_id, session['user_id'])
    )
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@login_required
def delete_task(task_id):
    db = get_db(DB_PATH)
    db.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, session['user_id']))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Schedule ──────────────────────────────────────────────────────────────
@app.route('/api/schedule', methods=['POST'])
@login_required
def schedule_task():
    data = request.json or {}
    result = scheduler.add(
        user_id=session['user_id'],
        title=data.get('title', ''),
        prompt=data.get('prompt', ''),
        run_at=data.get('run_at', ''),
        email=data.get('email', os.environ.get('GMAIL_ADDRESS', '')),
        db_path=DB_PATH
    )
    return jsonify(result)

@app.route('/api/schedule', methods=['GET'])
@login_required
def get_scheduled():
    tasks = scheduler.list_tasks(session['user_id'])
    return jsonify(tasks)

# ── Upload ────────────────────────────────────────────────────────────────
@app.route('/api/upload', methods=['POST'])
@login_required
def upload_file():
    from modules.file_handler import handle_upload
    if 'file' not in request.files:
        return jsonify({'error': 'Nenhum ficheiro'}), 400
    file = request.files['file']
    result = handle_upload(file, session['user_id'], DATA_DIR, get_ai_response)
    return jsonify(result)

# ── Stats ─────────────────────────────────────────────────────────────────
@app.route('/api/stats')
@login_required
def stats():
    user_id = session['user_id']
    db = get_db(DB_PATH)
    msgs = db.execute("SELECT COUNT(*) as c FROM conversations WHERE user_id=?", (user_id,)).fetchone()['c']
    tasks = db.execute("SELECT COUNT(*) as c FROM tasks WHERE user_id=?", (user_id,)).fetchone()['c']
    done = db.execute("SELECT COUNT(*) as c FROM tasks WHERE user_id=? AND status='done'", (user_id,)).fetchone()['c']
    mems = db.execute("SELECT COUNT(*) as c FROM memory WHERE user_id=?", (user_id,)).fetchone()['c']
    usage = db.execute(
        "SELECT provider, COUNT(*) as calls FROM ai_usage WHERE user_id=? GROUP BY provider ORDER BY calls DESC",
        (user_id,)
    ).fetchall()
    db.close()

    available = []
    for key, name in [('GEMINI_API_KEY','Gemini'), ('GROQ_API_KEY','Groq'),
                      ('OPENROUTER_API_KEY','OpenRouter'), ('CEREBRAS_API_KEY','Cerebras'),
                      ('MISTRAL_API_KEY','Mistral')]:
        if os.environ.get(key): available.append(f'{name} ✅')

    return jsonify({
        'messages': msgs, 'tasks': tasks, 'tasks_done': done, 'memories': mems,
        'ai_usage': [dict(r) for r in usage],
        'available_ais': available,
        'mode': 'paid' if IS_PAID else 'free',
        'data_dir': DATA_DIR,
        'scheduler_running': scheduler.is_running()
    })

# ── Reports ───────────────────────────────────────────────────────────────
@app.route('/api/report', methods=['POST'])
@login_required
def generate_report():
    from modules.reporter import generate
    data = request.json or {}
    report_type = data.get('type', 'daily')
    result = generate(session['user_id'], report_type, DB_PATH, DATA_DIR, get_ai_response)
    return jsonify(result)

# ── PIN ───────────────────────────────────────────────────────────────────
@app.route('/api/set-pin', methods=['POST'])
@login_required
def set_pin():
    data = request.json or {}
    pin = data.get('pin', '').strip()
    if len(pin) < 4:
        return jsonify({'error': 'PIN precisa de 4+ dígitos'}), 400
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    db = get_db(DB_PATH)
    db.execute("""INSERT INTO memory (user_id, category, key, value, updated_at)
        VALUES (?, 'sistema', 'pin_hash', ?, datetime('now'))
        ON CONFLICT(user_id, category, key) DO UPDATE SET value=excluded.value""",
        (session['user_id'], pin_hash))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/verify-pin', methods=['POST'])
@login_required
def verify_pin():
    data = request.json or {}
    pin_hash = hashlib.sha256(data.get('pin', '').encode()).hexdigest()
    db = get_db(DB_PATH)
    mem = db.execute(
        "SELECT value FROM memory WHERE user_id=? AND category='sistema' AND key='pin_hash'",
        (session['user_id'],)
    ).fetchone()
    db.close()
    if not mem: return jsonify({'error': 'PIN não configurado'}), 400
    if mem['value'] == pin_hash:
        session['pin_verified'] = True
        return jsonify({'ok': True})
    return jsonify({'error': 'PIN incorreto'}), 401

# ── Change Password ───────────────────────────────────────────────────────
@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.json or {}
    current_hash = hashlib.sha256(data.get('current', '').encode()).hexdigest()
    db = get_db(DB_PATH)
    user = db.execute("SELECT * FROM users WHERE id=? AND password_hash=?",
                      (session['user_id'], current_hash)).fetchone()
    if not user:
        db.close()
        return jsonify({'error': 'Password atual incorreta'}), 401
    new_pw = data.get('new', '')
    if len(new_pw) < 6:
        db.close()
        return jsonify({'error': 'Mínimo 6 caracteres'}), 400
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (hashlib.sha256(new_pw.encode()).hexdigest(), session['user_id']))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Notify Analysis ───────────────────────────────────────────────────────
@app.route('/api/notify-analysis', methods=['POST'])
@login_required
def notify_analysis():
    from modules.enricher import detect_and_enrich
    data = request.json or {}
    prompt = data.get('prompt', '')
    to_email = data.get('email', '')
    if not prompt or not to_email:
        return jsonify({'error': 'prompt e email obrigatórios'}), 400

    user_id = session['user_id']
    extra = detect_and_enrich(prompt, DB_PATH, user_id)
    messages = [{'role': 'user', 'content': prompt + extra}]
    response, model = get_ai_response(messages, '')

    db = get_db(DB_PATH)
    db.execute("INSERT INTO conversations (user_id, role, content) VALUES (?, 'user', ?)", (user_id, prompt))
    db.execute("INSERT INTO conversations (user_id, role, content, model_used) VALUES (?, 'assistant', ?, ?)",
               (user_id, response, model))
    db.commit()
    db.close()

    try:
        send_email(to_email, "✅ NEXUS — Análise Concluída!", response)
    except Exception as e:
        logger.error(f"Email error: {e}")

    return jsonify({'ok': True, 'response': response, 'model': model})


# ── SECURITY ENDPOINTS ────────────────────────────────────────────────────
@app.route('/api/security/audit', methods=['GET'])
@login_required
def get_audit():
    logs = get_audit_logs(session['user_id'], DB_PATH)
    return jsonify(logs)

@app.route('/api/security/emergency-stop', methods=['POST'])
@login_required
def trigger_emergency_stop():
    result = sec_emergency_stop(session['user_id'], DB_PATH)
    return jsonify(result)

@app.route('/api/security/emergency-resume', methods=['POST'])
@login_required
def trigger_emergency_resume():
    result = sec_emergency_resume(session['user_id'], DB_PATH)
    return jsonify(result)

@app.route('/api/security/status', methods=['GET'])
@login_required
def security_status():
    return jsonify({
        'emergency_stopped': is_emergency_stopped(),
        'mode': 'paid' if IS_PAID else 'free'
    })

@app.route('/api/security/check', methods=['POST'])
@login_required
def check_action():
    data = request.json or {}
    action = data.get('action', '')
    message = data.get('message', '')
    result = check_action_allowed(action, dict(session), message)
    level = classify_action_level(action)
    audit_log(session['user_id'], 'ACTION_CHECK', action, DB_PATH, level=level,
              result='allowed' if result['allowed'] else 'blocked')
    return jsonify(result)

# ── FINANCIAL ENDPOINTS ───────────────────────────────────────────────────
@app.route('/api/financial/config', methods=['GET'])
@login_required
def get_fin_config():
    return jsonify(get_financial_config(session['user_id'], DB_PATH))

@app.route('/api/financial/config', methods=['POST'])
@login_required
def set_fin_config():
    data = request.json or {}
    config = get_financial_config(session['user_id'], DB_PATH)
    config.update({k: v for k, v in data.items() if k in config})
    save_financial_config(session['user_id'], DB_PATH, config)
    audit_log(session['user_id'], 'CONFIG_UPDATE', 'Configuração financeira atualizada',
              DB_PATH, level=2)
    return jsonify({'ok': True, 'config': config})

@app.route('/api/financial/analyze', methods=['POST'])
@login_required
def analyze_investment():
    data = request.json or {}
    action = data.get('action', 'BUY')
    asset = data.get('asset', '')
    amount = float(data.get('amount', 0))
    if not asset or amount <= 0:
        return jsonify({'error': 'asset e amount obrigatórios'}), 400
    config = get_financial_config(session['user_id'], DB_PATH)
    result = analyze_investment_plan(config, action, asset, amount)
    audit_log(session['user_id'], 'INVESTMENT_ANALYSIS', f"{action} {amount}€ {asset}",
              DB_PATH, level=1)
    return jsonify(result)

@app.route('/api/financial/fact-check', methods=['POST'])
@login_required
def financial_fact_check():
    data = request.json or {}
    claim = data.get('claim', '')
    if not claim:
        return jsonify({'error': 'claim obrigatório'}), 400
    result = fact_check_investment_claim(claim, get_ai_response)
    return jsonify(result)

@app.route('/api/financial/portfolio', methods=['GET'])
@login_required
def get_portfolio():
    return jsonify(get_portfolio_summary(session['user_id'], DB_PATH))

@app.route('/api/financial/log-op', methods=['POST'])
@login_required
def log_financial_op():
    """Regista operação simulada."""
    data = request.json or {}
    log_operation(
        session['user_id'], DB_PATH,
        data.get('op_type', 'BUY'), data.get('asset', ''),
        float(data.get('amount', 0)), float(data.get('price', 0)),
        float(data.get('result', 0)), data.get('notes', '')
    )
    audit_log(session['user_id'], 'OP_LOG', f"{data.get('op_type')} {data.get('asset')}",
              DB_PATH, level=1)
    return jsonify({'ok': True})

# ── LEARNING ENDPOINTS ────────────────────────────────────────────────────
@app.route('/api/learning/analyze', methods=['POST'])
@login_required
def learning_analyze():
    result = analyze_conversation_patterns(session['user_id'], DB_PATH, get_ai_response)
    return jsonify(result)

@app.route('/api/learning/compare', methods=['POST'])
@login_required
def learning_compare():
    data = request.json or {}
    sources = data.get('sources', [])
    if not sources:
        return jsonify({'error': 'sources obrigatório'}), 400
    result = compare_sources(sources, get_ai_response)
    return jsonify(result)

@app.route('/api/learning/improve', methods=['POST'])
@login_required
def learning_improve():
    result = generate_improvement_plan(session['user_id'], DB_PATH, get_ai_response)
    return jsonify(result)

@app.route('/api/learning/history', methods=['GET'])
@login_required
def learning_hist():
    return jsonify(get_learning_history(session['user_id'], DB_PATH))

@app.route('/api/education', methods=['POST'])
@login_required
def education():
    data = request.json or {}
    topic = data.get('topic', '')
    level = data.get('level', 'beginner')
    if not topic:
        return jsonify({'error': 'topic obrigatório'}), 400
    result = investment_education(topic, level, get_ai_response)
    return jsonify(result)



# ── XTB ENDPOINTS ─────────────────────────────────────────────────────────
@app.route('/api/xtb/status', methods=['GET'])
@login_required
def xtb_status():
    """Verifica se XTB está configurado."""
    import os
    has_account = bool(os.environ.get('XTB_ACCOUNT_ID'))
    has_password = bool(os.environ.get('XTB_PASSWORD'))
    proxy = os.environ.get('XTB_PROXY', '')
    from urllib.parse import urlparse
    proxy_host = urlparse(proxy).hostname if proxy else None
    return jsonify({
        'configured':  has_account and has_password,
        'mode':        os.environ.get('XTB_MODE', 'demo'),
        'has_account': has_account,
        'has_password': has_password,
        'proxy':       proxy_host or None,
        'proxy_set':   bool(proxy),
    })

@app.route('/api/xtb/account', methods=['GET'])
@login_required
def xtb_account():
    """Consulta saldo XTB — requer PIN."""
    if not session.get('pin_verified'):
        return jsonify({'error': 'PIN necessário', 'needs': ['PIN']}), 401
    import os
    mode = os.environ.get('XTB_MODE', 'demo')
    session_data, err = xtb_login()
    if err:
        return jsonify({'error': err}), 400
    info, err2 = get_account_info(session_data)
    if err2:
        return jsonify({'error': err2}), 400
    audit_log(session['user_id'], 'XTB_ACCOUNT_QUERY', 'Consulta de saldo', DB_PATH, level=2)
    return jsonify({**info, 'mode': mode})

@app.route('/api/xtb/positions', methods=['GET'])
@login_required
def xtb_positions():
    """Consulta posições abertas."""
    if not session.get('pin_verified'):
        return jsonify({'error': 'PIN necessário'}), 401
    import os
    session_data, err = xtb_login(
        os.environ.get('XTB_ACCOUNT_ID',''),
        os.environ.get('XTB_PASSWORD',''),
        os.environ.get('XTB_MODE','demo')
    )
    if err: return jsonify({'error': err}), 400
    positions, err2 = get_positions(session_data)
    audit_log(session['user_id'], 'XTB_POSITIONS_QUERY', 'Consulta posições', DB_PATH, level=2)
    return jsonify({'positions': positions, 'error': err2})

@app.route('/api/xtb/price/<symbol>', methods=['GET'])
@login_required
def xtb_price(symbol):
    """Consulta preço de um símbolo."""
    price_data, err = get_asset_price(symbol)
    if err: return jsonify({'error': err}), 400
    return jsonify(price_data)

@app.route('/api/xtb/order', methods=['POST'])
@login_required
def xtb_order():
    """
    Executa ordem XTB.
    DEMO: requer PIN + "AUTORIZO EXECUÇÃO DEMO"
    REAL: requer WebAuthn + PIN + "AUTORIZO EXECUÇÃO REAL"
    """
    import os
    data = request.json or {}
    mode = os.environ.get('XTB_MODE', 'demo')
    auth_phrase = data.get('auth_phrase', '')
    action = f"ordem {data.get('cmd','?')} {data.get('amount_eur','?')}€ {data.get('symbol','?')} [{mode}]"

    # Frase correta por modo
    required_phrase = 'AUTORIZO EXECUÇÃO REAL' if mode == 'real' else 'AUTORIZO EXECUÇÃO DEMO'
    if auth_phrase.strip() != required_phrase:
        return jsonify({
            'error': f'Frase incorreta. Escreve exatamente: {required_phrase}',
            'required_phrase': required_phrase,
            'mode': mode
        }), 403

    # Nível de auth por modo
    if mode == 'real':
        auth = check_action_allowed(action, dict(session), auth_phrase)
        if not auth['allowed']:
            audit_log(session['user_id'], 'XTB_ORDER_BLOCKED', action, DB_PATH,
                      level=3, result='blocked', metadata=auth)
            return jsonify({'error': auth['reason'], 'needs': auth['needs'], 'mode': mode}), 403
    else:
        # DEMO: só PIN necessário
        if not session.get('pin_verified'):
            return jsonify({'error': 'PIN necessário para modo DEMO', 'needs': ['PIN'], 'mode': mode}), 403

    # Login XTB
    session_data, err = xtb_login(mode=mode)
    if err:
        audit_log(session['user_id'], 'XTB_LOGIN_FAIL', err, DB_PATH, level=2, result='error')
        return jsonify({'error': err, 'mode': mode}), 400

    # Executa ordem
    result, err2 = place_order(
        token=session_data['token'],
        symbol=data.get('symbol', ''),
        cmd=data.get('cmd', 'BUY'),
        amount_eur=float(data.get('amount_eur', 0)),
        price=float(data.get('price', 0)),
        sl_points=int(data.get('sl_points', 50)),
        tp_points=int(data.get('tp_points', 100)),
        mode=mode,
        user_id=session['user_id'],
        db_path=DB_PATH
    )

    level = 3 if mode == 'real' else 2
    audit_log(session['user_id'], 'XTB_ORDER', action, DB_PATH, level=level,
              result='ok' if result else 'error', metadata={'result': result, 'error': err2})

    if err2:
        return jsonify({'error': err2, 'mode': mode}), 400
    return jsonify({'ok': True, 'order': result, 'mode': mode})

@app.route('/api/xtb/history', methods=['GET'])
@login_required
def xtb_history():
    return jsonify(get_xtb_orders_history(session['user_id'], DB_PATH))

# ── MONITOR ENDPOINTS ──────────────────────────────────────────────────────
@app.route('/api/monitor/config', methods=['GET'])
@login_required
def get_mon_config():
    return jsonify(get_monitor_config(session['user_id'], DB_PATH))

@app.route('/api/monitor/config', methods=['POST'])
@login_required
def set_mon_config():
    data = request.json or {}
    config = get_monitor_config(session['user_id'], DB_PATH)
    config.update({k: v for k, v in data.items() if k in config})
    save_monitor_config(session['user_id'], DB_PATH, config)
    return jsonify({'ok': True, 'config': config})

@app.route('/api/monitor/assets', methods=['GET'])
@login_required
def get_assets():
    return jsonify(load_watched_assets(session['user_id'], DB_PATH))

@app.route('/api/monitor/assets', methods=['POST'])
@login_required
def add_asset():
    data = request.json or {}
    symbol = data.get('symbol', '').upper()
    if not symbol: return jsonify({'error': 'symbol obrigatório'}), 400
    market_monitor.add_asset(session['user_id'], DB_PATH, symbol, {
        'alert_below': float(data.get('alert_below', 0)),
        'alert_above': float(data.get('alert_above', 0))
    })
    return jsonify({'ok': True, 'symbol': symbol})

@app.route('/api/monitor/assets/<symbol>', methods=['DELETE'])
@login_required
def remove_asset(symbol):
    market_monitor.remove_asset(session['user_id'], DB_PATH, symbol.upper())
    return jsonify({'ok': True})

@app.route('/api/monitor/check', methods=['POST'])
@login_required
def force_check():
    """Força verificação imediata de todos os ativos."""
    alerts = market_monitor.force_check(session['user_id'], DB_PATH)
    return jsonify({'ok': True, 'alerts': alerts, 'count': len(alerts)})

@app.route('/api/monitor/price/<symbol>', methods=['GET'])
@login_required
def get_price(symbol):
    price_data, err = get_asset_price(symbol.upper())
    if err: return jsonify({'error': err}), 400
    return jsonify(price_data)

@app.route('/api/monitor/alerts', methods=['GET'])
@login_required
def get_alerts():
    return jsonify(get_recent_alerts(session['user_id'], DB_PATH))

@app.route('/api/monitor/status', methods=['GET'])
@login_required
def monitor_status():
    assets = load_watched_assets(session['user_id'], DB_PATH)
    config = get_monitor_config(session['user_id'], DB_PATH)
    return jsonify({
        'running': market_monitor.is_running(),
        'assets_count': len(assets),
        'assets': list(assets.keys()),
        'mode': config.get('mode', MODE_ASK),
        'check_interval': config.get('check_interval_min', 30)
    })

# ── SMS ENDPOINT ───────────────────────────────────────────────────────────
@app.route('/api/sms/send', methods=['POST'])
@login_required
def send_sms_endpoint():
    data = request.json or {}
    phone = data.get('phone', os.environ.get('USER_PHONE', ''))
    message = data.get('message', '')
    if not phone or not message:
        return jsonify({'error': 'phone e message obrigatórios'}), 400
    ok, result = send_sms(phone, message)
    return jsonify({'ok': ok, 'result': str(result)})

# ── EVOLUTION ENDPOINTS ────────────────────────────────────────────────────
@app.route('/api/evolution/generate', methods=['POST'])
@login_required
def evolution_generate():
    data = request.json or {}
    result = generate_code(
        data.get('task', ''),
        data.get('language', 'python'),
        data.get('context', ''),
        get_ai_response
    )
    return jsonify(result)

@app.route('/api/evolution/fix', methods=['POST'])
@login_required
def evolution_fix():
    data = request.json or {}
    result = analyze_and_fix(data.get('code', ''), data.get('error', ''), get_ai_response)
    return jsonify(result)

@app.route('/api/evolution/suggest', methods=['POST'])
@login_required
def evolution_suggest():
    data = request.json or {}
    module = data.get('module', '')
    content, err = read_module(module)
    if err: return jsonify({'error': err}), 400
    result = suggest_improvements(module, content, get_ai_response)
    return jsonify(result)

@app.route('/api/evolution/modules', methods=['GET'])
@login_required
def evolution_modules():
    return jsonify(list_modules())

@app.route('/api/evolution/new-module', methods=['POST'])
@login_required
def evolution_new_module():
    data = request.json or {}
    result = generate_new_module(
        data.get('name', ''), data.get('description', ''),
        data.get('requirements', ''), get_ai_response
    )
    return jsonify(result)



# ── MÓDULO 10 ENDPOINTS ───────────────────────────────────────────────────
@app.route('/api/mod10/status', methods=['GET'])
@login_required
def mod10_status():
    status = mod10.get_status(DB_PATH)
    return jsonify(status)

@app.route('/api/mod10/snapshot', methods=['POST'])
@login_required
def mod10_snapshot():
    snapshot = build_context_snapshot(DB_PATH, session['user_id'], get_ai_response)
    return jsonify({'ok': True, 'keys': list(snapshot.keys()), 'timestamp': snapshot.get('timestamp')})

@app.route('/api/mod10/context', methods=['GET'])
@login_required
def mod10_context():
    prompt = reconstruct_context_prompt(DB_PATH, session['user_id'])
    return jsonify({'context': prompt})

@app.route('/api/mod10/learn', methods=['POST'])
@login_required
def mod10_learn():
    result = learn_from_logs(DB_PATH, session['user_id'], get_ai_response)
    return jsonify(result)

@app.route('/api/mod10/health', methods=['POST'])
@login_required
def mod10_health():
    result = analyze_codebase_health(get_ai_response)
    return jsonify(result)

@app.route('/api/mod10/patch', methods=['POST'])
@login_required
def mod10_patch():
    data = request.json or {}
    issue = data.get('issue', '')
    if not issue:
        return jsonify({'error': 'issue obrigatório'}), 400
    patch = generate_self_patch(issue, get_ai_response, DB_PATH)
    return jsonify(patch)

@app.route('/api/mod10/patches', methods=['GET'])
@login_required
def mod10_patches():
    patches = get_pending_patches(DB_PATH)
    return jsonify(patches)

@app.route('/api/mod10/patches/<patch_hash>/approve', methods=['POST'])
@login_required
def mod10_approve_patch(patch_hash):
    if not session.get('pin_verified'):
        return jsonify({'error': 'PIN necessário'}), 401
    approve_patch(DB_PATH, patch_hash, session['username'])
    audit_log(session['user_id'], 'PATCH_APPROVED', f'Patch {patch_hash} aprovado',
              DB_PATH, level=2)
    return jsonify({'ok': True})

@app.route('/api/mod10/state', methods=['GET'])
@login_required
def mod10_get_state():
    key = request.args.get('key', 'last_cycle')
    value = load_state(DB_PATH, key)
    return jsonify({'key': key, 'value': value})



# ── TESTS ENDPOINTS ────────────────────────────────────────────────────────
@app.route('/api/tests/run', methods=['POST'])
@login_required
def run_tests():
    """Corre todos os testes automáticos."""
    from modules.tests import run_all_tests
    result = run_all_tests(DB_PATH)
    audit_log(session['user_id'], 'TESTS_RUN', f"Resultado: {result['passed']}/{result['total']}",
              DB_PATH, level=1, result='ok' if result['all_passed'] else 'fail')
    return jsonify(result)

@app.route('/api/tests/patch', methods=['POST'])
@login_required
def apply_patch_endpoint():
    """Aplica patch com testes e rollback automático. Requer PIN."""
    if not session.get('pin_verified'):
        return jsonify({'error': 'PIN necessário'}), 401
    data = request.json or {}
    patch_content = data.get('patch_content', '')
    target_file = data.get('target_file', '')
    run_tests_flag = data.get('run_tests', True)

    if not patch_content or not target_file:
        return jsonify({'error': 'patch_content e target_file obrigatórios'}), 400

    # Segurança: só permite ficheiros dentro do projeto
    import os
    base = os.path.dirname(os.path.abspath(__file__))
    target_abs = os.path.abspath(os.path.join(base, target_file))
    if not target_abs.startswith(base):
        return jsonify({'error': 'target_file fora do projeto'}), 403

    from modules.mod10 import apply_patch_safe
    result = apply_patch_safe(patch_content, target_abs, DB_PATH, run_tests_flag)

    audit_log(session['user_id'], 'PATCH_APPLIED', target_file, DB_PATH, level=2,
              result='ok' if result['success'] else 'error',
              metadata={'rolled_back': result.get('rolled_back')})
    return jsonify(result)

# ── XTB POSITION MONITOR ───────────────────────────────────────────────────
@app.route('/api/xtb/monitor/start', methods=['POST'])
@login_required
def xtb_monitor_start():
    """Inicia monitorização de posições abertas."""
    if not session.get('pin_verified'):
        return jsonify({'error': 'PIN necessário'}), 401

    data = request.json or {}
    interval_min = int(data.get('interval_min', 5))
    user_id = session['user_id']

    # Guarda configuração de monitorização XTB
    from modules.mod10 import save_state
    save_state(DB_PATH, 'xtb_monitor_config', {
        'active': True,
        'interval_min': interval_min,
        'user_id': user_id,
        'started_at': datetime.datetime.now().isoformat()
    })

    audit_log(user_id, 'XTB_MONITOR_START', f'Intervalo: {interval_min}min', DB_PATH, level=2)
    return jsonify({'ok': True, 'interval_min': interval_min})

@app.route('/api/xtb/monitor/status', methods=['GET'])
@login_required
def xtb_monitor_status():
    """Estado da monitorização XTB."""
    from modules.mod10 import load_state
    config = load_state(DB_PATH, 'xtb_monitor_config', default={})
    positions_cache = load_state(DB_PATH, 'xtb_positions_cache', default=[])
    return jsonify({
        'active': config.get('active', False),
        'interval_min': config.get('interval_min', 5),
        'started_at': config.get('started_at'),
        'cached_positions': len(positions_cache),
        'positions': positions_cache
    })

@app.route('/api/xtb/monitor/check', methods=['POST'])
@login_required
def xtb_monitor_check():
    """Força verificação imediata de posições XTB."""
    if not session.get('pin_verified'):
        return jsonify({'error': 'PIN necessário'}), 401

    import os
    mode = os.environ.get('XTB_MODE', 'demo')
    session_data, err = xtb_login(mode=mode)
    if err:
        return jsonify({'error': err, 'mode': mode}), 400

    positions, err2 = get_positions(session_data['token'])
    account, err3 = get_account_info(session_data['token'])

    # Cache das posições
    from modules.mod10 import save_state
    save_state(DB_PATH, 'xtb_positions_cache', positions)
    save_state(DB_PATH, 'xtb_account_cache', account or {})

    # Verifica limites nas posições abertas
    alerts = []
    config = {}
    try:
        from modules.financial import get_financial_config
        config = get_financial_config(session['user_id'], DB_PATH)
    except Exception:
        pass

    max_loss = config.get('max_loss_per_trade', 5.0)
    for pos in (positions or []):
        profit = pos.get('profit', 0)
        if profit < -max_loss:
            alerts.append({
                'symbol': pos.get('symbol'),
                'profit': profit,
                'alert': f"⚠️ {pos.get('symbol')} com perda de {profit:.2f}€ (limite: -{max_loss}€)"
            })

    # Envia alerta se há posições em risco
    if alerts:
        gmail = os.environ.get('GMAIL_ADDRESS', '')
        if gmail:
            alert_msg = "🔔 NEXUS — Alerta de Posições XTB\n\n"
            for a in alerts:
                alert_msg += a['alert'] + "\n"
            try:
                send_email(gmail, "⚠️ NEXUS XTB — Posições em Risco", alert_msg)
            except Exception:
                pass

    audit_log(session['user_id'], 'XTB_MONITOR_CHECK',
              f"{len(positions or [])} posições, {len(alerts)} alertas",
              DB_PATH, level=2)

    return jsonify({
        'ok': True,
        'mode': mode,
        'positions': positions or [],
        'account': account or {},
        'alerts': alerts,
        'errors': [e for e in [err2, err3] if e]
    })



# ── STATUS ENDPOINT ────────────────────────────────────────────────────────
@app.route('/api/health', methods=['GET'])
def api_health():
    """Health check público — sem autenticação. Usado por Render e monitores."""
    import os
    db_ok, db_detail = check_integrity(DB_PATH)
    disk_free = None
    try:
        st = os.statvfs(DATA_DIR)
        disk_free = st.f_bavail * st.f_frsize // (1024 * 1024)  # MB
    except Exception:
        pass
    status = 'ok' if db_ok else 'degraded'
    return jsonify({
        'status':     status,
        'db':         db_detail,
        'db_path':    DB_PATH,
        'disk_free_mb': disk_free,
        'mode':       'paid' if IS_PAID else 'free',
    }), (200 if db_ok else 503)


@app.route('/api/db/repair', methods=['POST'])
@login_required
def api_db_repair():
    """Força verificação e reparação da base de dados."""
    ok, detail = check_integrity(DB_PATH)
    if ok:
        return jsonify({'ok': True, 'message': f'DB íntegra: {detail}', 'repaired': False})
    logger.warning(f"DB repair solicitado — integrity: {detail}")
    repaired, msg = repair_db(DB_PATH)
    if repaired:
        try:
            init_db(DB_PATH)
        except Exception as e:
            return jsonify({'ok': False, 'message': f'repair ok mas init falhou: {e}'}), 500
    return jsonify({'ok': repaired, 'message': msg, 'repaired': repaired,
                    'integrity_before': detail})


@app.route('/api/status', methods=['GET'])
@login_required
def api_status():
    """AI router status: providers, mode, recent errors, quotas, timestamps."""
    status = get_router_status()
    status['nexus_mode'] = 'paid' if IS_PAID else 'free'
    status['scheduler_running'] = scheduler.is_running()
    status['emergency_stopped'] = is_emergency_stopped()
    db_ok, db_detail = check_integrity(DB_PATH)
    status['db_ok'] = db_ok
    status['db_detail'] = db_detail
    return jsonify(status)

@app.route('/api/status/reload', methods=['POST'])
@login_required
def api_status_reload():
    """Clears quota cooldowns and re-validates all providers (makes real API calls)."""
    results = reload_and_validate()
    return jsonify({'ok': True, 'results': results})


# ── DEBUG ENDPOINT (diagnóstico de API keys) ──────────────────────────────
@app.route('/api/debug/status', methods=['GET'])
@login_required
def debug_status():
    """Diagnóstico completo: keys, modelos, commands engine."""
    import os
    keys_status = {}
    for k in ['GEMINI_API_KEY','GROQ_API_KEY','OPENROUTER_API_KEY',
               'CEREBRAS_API_KEY','MISTRAL_API_KEY','SERPER_API_KEY',
               'GMAIL_ADDRESS','XTB_ACCOUNT_ID']:
        val = os.environ.get(k, '')
        keys_status[k] = 'SET' if val else 'MISSING'

    # Test command engine
    from modules.commands import parse_command
    test_cmds = [
        ('mostra limites atuais', 'show_limits'),
        ('liga xtb', 'connect_xtb'),
        ('iniciar sessão xtb demo', 'connect_xtb'),
    ]
    cmd_tests = []
    for phrase, expected in test_cmds:
        cmd, _, _ = parse_command(phrase)
        cmd_tests.append({'phrase': phrase, 'expected': expected, 'got': cmd, 'ok': cmd == expected})

    # Test ai_router (no actual API call)
    from modules.ai_router import _try_gemini
    import inspect
    ai_ok = callable(_try_gemini)

    return jsonify({
        'keys': keys_status,
        'command_tests': cmd_tests,
        'ai_router_ok': ai_ok,
        'emergency_stopped': is_emergency_stopped(),
        'xtb_mode': os.environ.get('XTB_MODE', 'demo'),
        'data_dir': DATA_DIR,
        'is_paid': IS_PAID,
    })

# ── Heartbeat ─────────────────────────────────────────────────────────────
@app.route('/api/heartbeat', methods=['GET', 'POST'])
def heartbeat():
    scheduler.check_and_run()
    return jsonify({'ok': True, 'mode': 'paid' if IS_PAID else 'free',
                    'time': datetime.datetime.now().isoformat()})

# ── Logs ──────────────────────────────────────────────────────────────────
@app.route('/api/logs')
@login_required
def get_logs():
    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()[-100:]
        return jsonify({'logs': ''.join(lines)})
    except Exception:
        return jsonify({'logs': 'Sem logs disponíveis'})

# ── Reset (emergency) ─────────────────────────────────────────────────────
@app.route('/reset/<token>')
def emergency_reset(token):
    if token != os.environ.get('RESET_TOKEN', 'nexus-reset-2024'):
        return '<h2>Token inválido</h2>', 403
    try:
        os.remove(DB_PATH)
    except Exception:
        pass
    init_db(DB_PATH)
    return '<h2>✅ Reset feito! <a href="/">Voltar</a></h2>'

# ── Static ────────────────────────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join('static', path)):
        return send_from_directory('static', path)
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
