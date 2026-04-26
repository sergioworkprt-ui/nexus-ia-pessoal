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

# ── Import modules ────────────────────────────────────────────────────────
from modules.database import init_db, get_db
from modules.ai_router import get_ai_response
from modules.email_sender import send_email
from modules.youtube import get_youtube_transcript
from modules.scheduler import scheduler
from modules.notifications import notify

# Inicializa DB e scheduler
init_db(DB_PATH)
scheduler.start(DB_PATH, get_ai_response, send_email)

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
    from modules.enricher import detect_and_enrich
    data = request.json or {}
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'error': 'Mensagem vazia'}), 400

    user_id = session['user_id']
    db = get_db(DB_PATH)

    # Guarda mensagem do utilizador
    db.execute("INSERT INTO conversations (user_id, role, content) VALUES (?, 'user', ?)",
               (user_id, user_message))
    db.commit()

    # Carrega histórico (últimas 20 mensagens)
    history = db.execute(
        "SELECT role, content FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 20",
        (user_id,)
    ).fetchall()
    db.close()

    messages = [{'role': r['role'], 'content': r['content']} for r in reversed(history)]

    # Enriquece com contexto (YouTube, web search, etc.)
    extra = detect_and_enrich(user_message, DB_PATH, user_id)
    if extra:
        messages[-1]['content'] += extra

    # Carrega memória do utilizador
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

    # Guarda resposta
    db = get_db(DB_PATH)
    db.execute(
        "INSERT INTO conversations (user_id, role, content, model_used) VALUES (?, 'assistant', ?, ?)",
        (user_id, ai_response, model_used)
    )
    db.commit()
    db.close()

    logger.info(f"Chat [{model_used}] user={user_id} chars={len(ai_response)}")

    # Auto-email se pedido
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
