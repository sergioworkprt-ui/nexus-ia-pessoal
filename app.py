import os
import json
import hashlib
import secrets
import sqlite3
import urllib.request
import urllib.error
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory

app = Flask(__name__, static_folder='static')
# SECRET_KEY deve ser fixo para sessões persistirem entre restarts
_default_key = 'nexus-secret-key-default-2024-change-this'
app.secret_key = os.environ.get('SECRET_KEY', _default_key)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # True se HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7 dias

# ── Database ──────────────────────────────────────────────────────────────
DB_PATH = 'data/agent.db'

def get_db():
    os.makedirs('data', exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    # Reset DB if RESET_DB env var is set
    if os.environ.get('RESET_DB') == 'true':
        try:
            os.remove(DB_PATH)
        except Exception:
            pass

    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            model_used TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, category, key),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS ai_usage (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            tokens_approx INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'nexus-2024')
    pw_hash = hashlib.sha256(admin_pass.encode()).hexdigest()
    try:
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ('admin', pw_hash))
        db.commit()
    except Exception:
        pass
    db.close()

init_db()

# ── Auth ──────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Não autenticado'}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    pw_hash = hashlib.sha256(data.get('password', '').encode()).hexdigest()
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=? AND password_hash=?",
                      (data.get('username', '').strip(), pw_hash)).fetchone()
    db.close()
    if user:
        session.permanent = True
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({'ok': True, 'username': user['username']})
    return jsonify({'error': 'Credenciais inválidas'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/me')
@login_required
def me():
    return jsonify({'username': session['username'], 'user_id': session['user_id']})

# ── Sistema de Prompt ─────────────────────────────────────────────────────
SYSTEM_PROMPT = """És uma IA pessoal e autónoma chamada NEXUS. Trabalhas exclusivamente para o teu utilizador Sergio, de Portugal (Paredes, Porto).

A tua missão principal é ajudar o Sergio a:
1. GERAR RENDIMENTO online através de métodos legais e éticos
2. AUTOMATIZAR tarefas repetitivas e de pesquisa
3. CRIAR conteúdo de qualidade (artigos, posts, scripts, emails, guiões)
4. PLANEAR e EXECUTAR estratégias de negócio digital
5. EVOLUIR continuamente — aprender com os resultados e adaptar as estratégias

Quando sugeres formas de gerar rendimento, sê ESPECÍFICO e REALISTA:
- Método concreto e detalhado (não vago)
- Esforço inicial necessário (horas/semana)
- Potencial de rendimento estimado em euros/mês
- Primeiros 3 passos de ação IMEDIATA que o Sergio pode fazer hoje

Usa SEMPRE a memória disponível para personalizar as respostas.
Idioma: responde SEMPRE em Português de Portugal (não brasileiro).
Tom: direto, prático, orientado a resultados. Como um sócio de negócios experiente."""

# ── AI Router ─────────────────────────────────────────────────────────────
def make_request(url, headers, body):
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8')), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8')[:300]}"
    except Exception as e:
        return None, str(e)[:200]

def try_gemini(messages, memory_context):
    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        return None, "GEMINI_API_KEY não definida"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    contents = []
    for msg in messages:
        role = 'user' if msg['role'] == 'user' else 'model'
        contents.append({'role': role, 'parts': [{'text': msg['content']}]})
    body = {
        'system_instruction': {'parts': [{'text': SYSTEM_PROMPT + memory_context}]},
        'contents': contents,
        'generationConfig': {'maxOutputTokens': 2048, 'temperature': 0.7}
    }
    result, err = make_request(url, {'Content-Type': 'application/json'}, body)
    if err:
        return None, f"Gemini: {err}"
    try:
        return result['candidates'][0]['content']['parts'][0]['text'], None
    except Exception as e:
        return None, f"Gemini parse: {e}"

def try_groq(messages, memory_context):
    api_key = os.environ.get('GROQ_API_KEY', '')
    if not api_key:
        return None, "GROQ_API_KEY não definida"
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}
    msgs = [{'role': 'system', 'content': SYSTEM_PROMPT + memory_context}]
    msgs += [{'role': m['role'], 'content': m['content']} for m in messages]
    body = {'model': 'llama3-70b-8192', 'messages': msgs, 'max_tokens': 2048, 'temperature': 0.7}
    result, err = make_request(url, headers, body)
    if err:
        return None, f"Groq: {err}"
    try:
        return result['choices'][0]['message']['content'], None
    except Exception as e:
        return None, f"Groq parse: {e}"

def try_openrouter(messages, memory_context):
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        return None, "OPENROUTER_API_KEY não definida"
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}',
        'HTTP-Referer': 'https://nexus-ia-pessoal.onrender.com',
        'X-Title': 'NEXUS IA Pessoal'
    }
    msgs = [{'role': 'system', 'content': SYSTEM_PROMPT + memory_context}]
    msgs += [{'role': m['role'], 'content': m['content']} for m in messages]
    free_models = [
        'google/gemini-flash-1.5',
        'meta-llama/llama-3.3-70b-instruct:free',
        'mistralai/mistral-7b-instruct:free',
        'microsoft/phi-3-medium-128k-instruct:free',
    ]
    for model in free_models:
        body = {'model': model, 'messages': msgs, 'max_tokens': 2048}
        result, err = make_request(url, headers, body)
        if not err:
            try:
                text = result['choices'][0]['message']['content']
                if text:
                    return text, None
            except Exception:
                continue
    return None, "OpenRouter: todos os modelos gratuitos falharam"

def try_mistral(messages, memory_context):
    api_key = os.environ.get('MISTRAL_API_KEY', '')
    if not api_key:
        return None, "MISTRAL_API_KEY não definida"
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}
    msgs = [{'role': 'system', 'content': SYSTEM_PROMPT + memory_context}]
    msgs += [{'role': m['role'], 'content': m['content']} for m in messages]
    body = {'model': 'mistral-small-latest', 'messages': msgs, 'max_tokens': 2048, 'temperature': 0.7}
    result, err = make_request(url, headers, body)
    if err:
        return None, f"Mistral: {err}"
    try:
        return result['choices'][0]['message']['content'], None
    except Exception as e:
        return None, f"Mistral parse: {e}"


def try_cerebras(messages, memory_context):
    api_key = os.environ.get('CEREBRAS_API_KEY', '')
    if not api_key:
        return None, "CEREBRAS_API_KEY não definida"
    url = "https://api.cerebras.ai/v1/chat/completions"
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}
    msgs = [{'role': 'system', 'content': SYSTEM_PROMPT + memory_context}]
    msgs += [{'role': m['role'], 'content': m['content']} for m in messages]
    body = {'model': 'llama-3.3-70b', 'messages': msgs, 'max_tokens': 2048, 'temperature': 0.7}
    result, err = make_request(url, headers, body)
    if err:
        return None, f"Cerebras: {err}"
    try:
        return result['choices'][0]['message']['content'], None
    except Exception as e:
        return None, f"Cerebras parse: {e}"

def web_search(query):
    """Pesquisa Google via Serper API."""
    api_key = os.environ.get('SERPER_API_KEY', '')
    if not api_key:
        return None
    url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
    body = {'q': query, 'gl': 'pt', 'hl': 'pt', 'num': 5}
    result, err = make_request(url, headers, body)
    if err or not result:
        return None
    results = []
    for r in result.get('organic', [])[:5]:
        results.append(f"• {r.get('title','')}: {r.get('snippet','')} ({r.get('link','')})")
    return "\n".join(results) if results else None

def get_youtube_transcript(url_or_id):
    """Extrai transcrição de vídeo YouTube via API pública."""
    import re
    vid_match = re.search(r'(?:v=|youtu\.be/|embed/)([\w-]{11})', url_or_id)
    video_id = vid_match.group(1) if vid_match else url_or_id.strip()
    if len(video_id) != 11:
        return None, "ID de vídeo inválido"
    try:
        # Tenta via timedtext API pública do YouTube
        langs = ['pt', 'pt-PT', 'pt-BR', 'en']
        for lang in langs:
            api_url = f"https://www.youtube.com/api/timedtext?v={video_id}&lang={lang}&fmt=json3"
            req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                events = data.get('events', [])
                if events:
                    text = ' '.join(
                        seg.get('utf8', '') 
                        for e in events 
                        for seg in e.get('segs', [])
                        if seg.get('utf8', '').strip()
                    )
                    if text.strip():
                        return text[:4000], None
        return None, "Transcrição não disponível neste vídeo"
    except Exception as e:
        return None, f"Erro: {str(e)[:100]}"

def detect_and_enrich(user_message, messages):
    """Deteta pedidos de pesquisa web ou YouTube e enriquece o contexto."""
    msg_lower = user_message.lower()
    extra_context = ""
    
    # Deteta pedido de pesquisa web
    search_triggers = ['pesquisa', 'pesquisar', 'procura', 'procurar', 'busca', 'buscar', 
                       'search', 'o que é', 'o que são', 'como funciona', 'notícias', 
                       'preço de', 'quanto custa', 'melhor', 'top ', 'ranking']
    is_search = any(t in msg_lower for t in search_triggers)
    
    # Deteta link YouTube
    is_youtube = 'youtube.com' in msg_lower or 'youtu.be' in msg_lower
    
    if is_youtube:
        import re
        urls = re.findall(r'https?://[^\s]+', user_message)
        for url in urls:
            if 'youtube' in url or 'youtu.be' in url:
                transcript, err = get_youtube_transcript(url)
                if transcript:
                    extra_context += f"\n\nTRANSCRIÇÃO DO VÍDEO YOUTUBE:\n{transcript}\n"
                else:
                    extra_context += f"\n\n[Não foi possível obter transcrição: {err}]\n"
                break
    elif is_search and os.environ.get('SERPER_API_KEY'):
        # Extrai query de pesquisa
        query = user_message
        for prefix in ['pesquisa ', 'pesquisar ', 'procura ', 'procurar ', 'busca ', 'search ']:
            if msg_lower.startswith(prefix):
                query = user_message[len(prefix):]
                break
        results = web_search(query)
        if results:
            extra_context += f"\n\nRESULTADOS DA PESQUISA WEB PARA: {query}\n{results}\n"
    
    return extra_context

def get_ai_response(messages, user_id):
    db = get_db()
    memories = db.execute(
        "SELECT category, key, value FROM memory WHERE user_id=?", (user_id,)
    ).fetchall()
    db.close()

    memory_context = ""
    if memories:
        memory_context = "\n\nMEMÓRIA PERSISTENTE DO UTILIZADOR SERGIO:\n"
        for m in memories:
            memory_context += f"  [{m['category']}] {m['key']}: {m['value']}\n"

    # Ordem: melhor gratuito primeiro
    providers = [
        ('Gemini 1.5 Flash', try_gemini),
        ('Groq Llama 3.3 70B', try_groq),
        ('Cerebras Llama 3.3', try_cerebras),
        ('OpenRouter', try_openrouter),
        ('Mistral', try_mistral),
    ]

    errors = []
    for name, fn in providers:
        response, err = fn(messages, memory_context)
        if response:
            db = get_db()
            db.execute(
                "INSERT INTO ai_usage (user_id, provider, model, tokens_approx) VALUES (?, ?, ?, ?)",
                (user_id, name, name, len(str(messages)) // 4)
            )
            db.commit()
            db.close()
            return response, name
        errors.append(f"{name}: {err}")

    msg = "⚠️ Nenhuma IA disponível. Configura pelo menos uma API Key no Render:\n\n"
    msg += "• GEMINI_API_KEY → aistudio.google.com (gratuito)\n"
    msg += "• GROQ_API_KEY → console.groq.com (gratuito)\n"
    msg += "• OPENROUTER_API_KEY → openrouter.ai (gratuito)\n"
    msg += "• MISTRAL_API_KEY → console.mistral.ai (gratuito)\n\n"
    msg += "Erros: " + " | ".join(errors[:2])
    return msg, "none"

# ── Chat ──────────────────────────────────────────────────────────────────
@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    data = request.json
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'error': 'Mensagem vazia'}), 400
    user_id = session['user_id']
    db = get_db()
    db.execute("INSERT INTO conversations (user_id, role, content) VALUES (?, 'user', ?)",
               (user_id, user_message))
    db.commit()
    history = db.execute(
        "SELECT role, content FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 20",
        (user_id,)
    ).fetchall()
    db.close()
    messages = [{'role': r['role'], 'content': r['content']} for r in reversed(history)]
    
    # Enriquece com pesquisa web ou YouTube se necessário
    extra = detect_and_enrich(user_message, messages)
    if extra:
        messages[-1]['content'] = messages[-1]['content'] + extra
    
    ai_response, model_used = get_ai_response(messages, user_id)
    db = get_db()
    db.execute(
        "INSERT INTO conversations (user_id, role, content, model_used) VALUES (?, 'assistant', ?, ?)",
        (user_id, ai_response, model_used)
    )
    db.commit()
    db.close()
    return jsonify({'response': ai_response, 'model': model_used})

@app.route('/api/history')
@login_required
def history():
    db = get_db()
    rows = db.execute(
        "SELECT role, content, model_used, created_at FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 60",
        (session['user_id'],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in reversed(rows)])

@app.route('/api/clear-history', methods=['POST'])
@login_required
def clear_history():
    db = get_db()
    db.execute("DELETE FROM conversations WHERE user_id=?", (session['user_id'],))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Tasks ─────────────────────────────────────────────────────────────────
@app.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    db = get_db()
    rows = db.execute("SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC",
                      (session['user_id'],)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/tasks', methods=['POST'])
@login_required
def create_task():
    data = request.json
    db = get_db()
    db.execute("INSERT INTO tasks (user_id, title, description, status) VALUES (?, ?, ?, 'pending')",
               (session['user_id'], data.get('title'), data.get('description', '')))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/tasks/<int:task_id>', methods=['PATCH'])
@login_required
def update_task(task_id):
    data = request.json
    db = get_db()
    db.execute("UPDATE tasks SET status=?, result=?, updated_at=datetime('now') WHERE id=? AND user_id=?",
               (data.get('status'), data.get('result', ''), task_id, session['user_id']))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@login_required
def delete_task(task_id):
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, session['user_id']))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Memory ────────────────────────────────────────────────────────────────
@app.route('/api/memory', methods=['GET'])
@login_required
def get_memory():
    db = get_db()
    rows = db.execute("SELECT * FROM memory WHERE user_id=? ORDER BY category, key",
                      (session['user_id'],)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/memory', methods=['POST'])
@login_required
def set_memory():
    data = request.json
    db = get_db()
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
    db = get_db()
    db.execute("DELETE FROM memory WHERE id=? AND user_id=?", (mem_id, session['user_id']))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Stats ─────────────────────────────────────────────────────────────────
@app.route('/api/stats')
@login_required
def stats():
    user_id = session['user_id']
    db = get_db()
    total_msgs  = db.execute("SELECT COUNT(*) as c FROM conversations WHERE user_id=?", (user_id,)).fetchone()['c']
    total_tasks = db.execute("SELECT COUNT(*) as c FROM tasks WHERE user_id=?", (user_id,)).fetchone()['c']
    done_tasks  = db.execute("SELECT COUNT(*) as c FROM tasks WHERE user_id=? AND status='done'", (user_id,)).fetchone()['c']
    total_mem   = db.execute("SELECT COUNT(*) as c FROM memory WHERE user_id=?", (user_id,)).fetchone()['c']
    usage_rows  = db.execute(
        "SELECT provider, COUNT(*) as calls FROM ai_usage WHERE user_id=? GROUP BY provider ORDER BY calls DESC",
        (user_id,)
    ).fetchall()
    db.close()
    available = []
    if os.environ.get('GEMINI_API_KEY'):      available.append('Gemini ✅')
    if os.environ.get('GROQ_API_KEY'):        available.append('Groq ✅')
    if os.environ.get('OPENROUTER_API_KEY'):  available.append('OpenRouter ✅')
    if os.environ.get('MISTRAL_API_KEY'):     available.append('Mistral ✅')
    if not available: available = ['Nenhuma configurada ⚠️']
    return jsonify({
        'messages': total_msgs, 'tasks': total_tasks,
        'tasks_done': done_tasks, 'memories': total_mem,
        'ai_usage': [dict(r) for r in usage_rows],
        'available_ais': available
    })

# ── Password ──────────────────────────────────────────────────────────────
@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.json
    current_hash = hashlib.sha256(data.get('current', '').encode()).hexdigest()
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=? AND password_hash=?",
                      (session['user_id'], current_hash)).fetchone()
    if not user:
        db.close()
        return jsonify({'error': 'Password atual incorreta'}), 401
    new_pw = data.get('new', '')
    if len(new_pw) < 6:
        db.close()
        return jsonify({'error': 'Mínimo 6 caracteres'}), 400
    new_hash = hashlib.sha256(new_pw.encode()).hexdigest()
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (new_hash, session['user_id']))
    db.commit()
    db.close()
    return jsonify({'ok': True, 'message': 'Password alterada com sucesso!'})


# ── Email Notifications (Gmail SMTP) ─────────────────────────────────────
def send_email(to_email, subject, body):
    """Envia email via Gmail SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    
    gmail = os.environ.get('GMAIL_ADDRESS', '')
    app_password = os.environ.get('GMAIL_APP_PASSWORD', '')
    
    if not gmail or not app_password:
        return False, "Gmail não configurado. Adiciona GMAIL_ADDRESS e GMAIL_APP_PASSWORD no Render."
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"NEXUS IA Pessoal <{gmail}>"
        msg['To'] = to_email
        
        # Texto simples
        text_part = MIMEText(body, 'plain', 'utf-8')
        msg.attach(text_part)
        
        # HTML bonito
        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#0a0a0f;color:#e8e8f0;padding:2rem;border-radius:12px">
            <h1 style="color:#a594ff;border-bottom:1px solid #2a2a3a;padding-bottom:1rem">⚡ NEXUS — Análise Concluída</h1>
            <div style="background:#1a1a24;padding:1.5rem;border-radius:8px;border:1px solid #2a2a3a;white-space:pre-wrap;line-height:1.6">{body}</div>
            <p style="margin-top:1.5rem;color:#5a5a7a;font-size:0.8rem">
                Acede à tua NEXUS: <a href="https://nexus-ia-pessoal.onrender.com" style="color:#7c6fff">nexus-ia-pessoal.onrender.com</a>
            </p>
        </div>
        """
        html_part = MIMEText(html_body, 'html', 'utf-8')
        msg.attach(html_part)
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail, app_password)
            server.sendmail(gmail, to_email, msg.as_string())
        
        return True, None
    except Exception as e:
        return False, str(e)

@app.route('/api/send-email', methods=['POST'])
@login_required
def send_email_endpoint():
    data = request.json
    to_email = data.get('to', '')
    subject = data.get('subject', 'Mensagem da NEXUS')
    body = data.get('body', '')
    if not to_email or not body:
        return jsonify({'error': 'Email e mensagem obrigatórios'}), 400
    ok, err = send_email(to_email, subject, body)
    if ok:
        return jsonify({'ok': True})
    return jsonify({'error': err}), 500

@app.route('/api/notify-analysis', methods=['POST'])
@login_required
def notify_analysis():
    """Faz análise longa e envia email quando terminar."""
    data = request.json
    user_id = session['user_id']
    prompt = data.get('prompt', '')
    to_email = data.get('email', '')
    if not prompt or not to_email:
        return jsonify({'error': 'Prompt e email obrigatórios'}), 400
    
    # Faz a análise
    messages = [{'role': 'user', 'content': prompt}]
    response, model = get_ai_response(messages, user_id)
    
    # Guarda na conversa
    db = get_db()
    db.execute("INSERT INTO conversations (user_id, role, content) VALUES (?, 'user', ?)",
               (user_id, prompt))
    db.execute("INSERT INTO conversations (user_id, role, content, model_used) VALUES (?, 'assistant', ?, ?)",
               (user_id, response, model))
    db.commit()
    db.close()
    
    # Envia email
    subject = "✅ NEXUS — Análise Concluída!"
    email_body = f"""Olá Sergio!

A tua NEXUS terminou a análise que pediste.

RESPOSTA:
{response}

---
Modelo usado: {model}
Acede à NEXUS: https://nexus-ia-pessoal.onrender.com
"""
    send_email(to_email, subject, email_body)
    return jsonify({'ok': True, 'response': response, 'model': model})

# ── Emergency Reset ───────────────────────────────────────────────────────
@app.route("/reset/<token>")
def emergency_reset(token):
    expected = os.environ.get("RESET_TOKEN", "nexus-reset-2024")
    if token != expected:
        return "<h2>Token invalido</h2>", 403
    try:
        os.remove(DB_PATH)
    except Exception:
        pass
    init_db()
    return "<h2>Reset feito! Vai para a NEXUS e faz login.</h2>"

# ── Static ────────────────────────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join('static', path)):
        return send_from_directory('static', path)
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
