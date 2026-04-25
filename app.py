import os
import json
import hashlib
import secrets
import sqlite3
import datetime
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory
import anthropic

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# ── Database ──────────────────────────────────────────────────────────────
DB_PATH = 'data/agent.db'

def get_db():
    os.makedirs('data', exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
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
    """)
    # Create default admin user if none exists
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'minha-ia-2024')
    pw_hash = hashlib.sha256(admin_pass.encode()).hexdigest()
    try:
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                   ('admin', pw_hash))
        db.commit()
    except Exception:
        pass
    db.close()

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
    username = data.get('username', '').strip()
    password = data.get('password', '')
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=? AND password_hash=?",
                      (username, pw_hash)).fetchone()
    db.close()
    if user:
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

# ── AI Chat ───────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """És uma IA pessoal e autónoma chamada NEXUS. Trabalhas exclusivamente para o teu utilizador.

A tua missão principal é ajudar o utilizador a:
1. GERAR RENDIMENTO online através de métodos legais e éticos
2. AUTOMATIZAR tarefas repetitivas e de pesquisa
3. CRIAR conteúdo de qualidade (artigos, posts, scripts, emails)
4. PLANEAR e EXECUTAR estratégias de negócio digital
5. APRENDER e MELHORAR continuamente com base nos resultados

Tens acesso a:
- Memória persistente do utilizador (preferências, projetos, resultados)
- Lista de tarefas ativas
- Histórico de conversas

Quando sugeres formas de gerar rendimento, sê específico e realista. Apresenta:
- O método concreto
- O esforço inicial necessário
- O potencial de rendimento estimado
- Os primeiros 3 passos de ação

Idioma: responde sempre em Português de Portugal.
Sê direto, prático e orientado a resultados. Evita respostas vagas."""

def get_ai_response(messages, user_id):
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return "⚠️ API Key não configurada. Vai a Configurações e adiciona a tua chave ANTHROPIC_API_KEY."
    
    client = anthropic.Anthropic(api_key=api_key)
    
    # Load user memory
    db = get_db()
    memories = db.execute("SELECT category, key, value FROM memory WHERE user_id=?", 
                          (user_id,)).fetchall()
    db.close()
    
    memory_context = ""
    if memories:
        memory_context = "\n\nMEMÓRIA DO UTILIZADOR:\n"
        for m in memories:
            memory_context += f"- [{m['category']}] {m['key']}: {m['value']}\n"
    
    system = SYSTEM_PROMPT + memory_context
    
    try:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            system=system,
            messages=messages
        )
        return response.content[0].text
    except Exception as e:
        return f"Erro ao contactar a IA: {str(e)}"

@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    data = request.json
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'error': 'Mensagem vazia'}), 400
    
    user_id = session['user_id']
    db = get_db()
    
    # Save user message
    db.execute("INSERT INTO conversations (user_id, role, content) VALUES (?, 'user', ?)",
               (user_id, user_message))
    db.commit()
    
    # Load conversation history (last 20 messages)
    history = db.execute(
        "SELECT role, content FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 20",
        (user_id,)
    ).fetchall()
    
    messages = [{'role': r['role'], 'content': r['content']} for r in reversed(history)]
    
    # Get AI response
    ai_response = get_ai_response(messages, user_id)
    
    # Save assistant response
    db.execute("INSERT INTO conversations (user_id, role, content) VALUES (?, 'assistant', ?)",
               (user_id, ai_response))
    db.commit()
    db.close()
    
    return jsonify({'response': ai_response})

@app.route('/api/history')
@login_required
def history():
    user_id = session['user_id']
    db = get_db()
    rows = db.execute(
        "SELECT role, content, created_at FROM conversations WHERE user_id=? ORDER BY id DESC LIMIT 50",
        (user_id,)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in reversed(rows)])

@app.route('/api/clear-history', methods=['POST'])
@login_required
def clear_history():
    user_id = session['user_id']
    db = get_db()
    db.execute("DELETE FROM conversations WHERE user_id=?", (user_id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Tasks ─────────────────────────────────────────────────────────────────
@app.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    user_id = session['user_id']
    db = get_db()
    rows = db.execute(
        "SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/tasks', methods=['POST'])
@login_required
def create_task():
    data = request.json
    user_id = session['user_id']
    db = get_db()
    db.execute(
        "INSERT INTO tasks (user_id, title, description, status) VALUES (?, ?, ?, 'pending')",
        (user_id, data.get('title'), data.get('description', ''))
    )
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/tasks/<int:task_id>', methods=['PATCH'])
@login_required
def update_task(task_id):
    data = request.json
    user_id = session['user_id']
    db = get_db()
    db.execute(
        "UPDATE tasks SET status=?, result=?, updated_at=datetime('now') WHERE id=? AND user_id=?",
        (data.get('status'), data.get('result', ''), task_id, user_id)
    )
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@login_required
def delete_task(task_id):
    user_id = session['user_id']
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Memory ────────────────────────────────────────────────────────────────
@app.route('/api/memory', methods=['GET'])
@login_required
def get_memory():
    user_id = session['user_id']
    db = get_db()
    rows = db.execute("SELECT * FROM memory WHERE user_id=? ORDER BY category, key",
                      (user_id,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/memory', methods=['POST'])
@login_required
def set_memory():
    data = request.json
    user_id = session['user_id']
    db = get_db()
    db.execute(
        """INSERT INTO memory (user_id, category, key, value, updated_at) 
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(user_id, category, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (user_id, data.get('category', 'geral'), data.get('key'), data.get('value'))
    )
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/memory/<int:mem_id>', methods=['DELETE'])
@login_required
def delete_memory(mem_id):
    user_id = session['user_id']
    db = get_db()
    db.execute("DELETE FROM memory WHERE id=? AND user_id=?", (mem_id, user_id))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Stats ─────────────────────────────────────────────────────────────────
@app.route('/api/stats')
@login_required
def stats():
    user_id = session['user_id']
    db = get_db()
    total_msgs = db.execute("SELECT COUNT(*) as c FROM conversations WHERE user_id=?", (user_id,)).fetchone()['c']
    total_tasks = db.execute("SELECT COUNT(*) as c FROM tasks WHERE user_id=?", (user_id,)).fetchone()['c']
    done_tasks = db.execute("SELECT COUNT(*) as c FROM tasks WHERE user_id=? AND status='done'", (user_id,)).fetchone()['c']
    total_mem = db.execute("SELECT COUNT(*) as c FROM memory WHERE user_id=?", (user_id,)).fetchone()['c']
    db.close()
    return jsonify({
        'messages': total_msgs,
        'tasks': total_tasks,
        'tasks_done': done_tasks,
        'memories': total_mem
    })

# ── Change Password ───────────────────────────────────────────────────────
@app.route('/api/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.json
    user_id = session['user_id']
    current = data.get('current', '')
    new_pw = data.get('new', '')
    if len(new_pw) < 6:
        return jsonify({'error': 'A nova password precisa de pelo menos 6 caracteres'}), 400
    current_hash = hashlib.sha256(current.encode()).hexdigest()
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=? AND password_hash=?",
                      (user_id, current_hash)).fetchone()
    if not user:
        db.close()
        return jsonify({'error': 'Password atual incorreta'}), 401
    new_hash = hashlib.sha256(new_pw.encode()).hexdigest()
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user_id))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Static Files ──────────────────────────────────────────────────────────
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
