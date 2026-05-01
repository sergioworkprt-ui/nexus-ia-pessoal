"""Database module — SQLite com suporte a /data persistente."""
import sqlite3

def get_db(db_path):
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL mode: permite leituras concorrentes com escritas sem bloquear
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")  # 30s retry antes de desistir
    conn.execute("PRAGMA synchronous=NORMAL")  # equilíbrio entre segurança e velocidade
    return conn

def init_db(db_path):
    import hashlib, os
    db = get_db(db_path)
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
            run_at TEXT,
            email TEXT,
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
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            title TEXT NOT NULL,
            body TEXT,
            read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)

    # Cria utilizador admin se não existir
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'nexus2024')
    pw_hash = hashlib.sha256(admin_pass.encode()).hexdigest()
    try:
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ('admin', pw_hash))
        db.commit()
    except Exception:
        pass
    db.close()
