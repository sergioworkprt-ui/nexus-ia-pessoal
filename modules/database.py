"""Database module — SQLite robusto com WAL, retry automático e auto-repair."""
import sqlite3, threading, time, logging, os, shutil, hashlib

logger = logging.getLogger('nexus.db')

# Erros transientes que valem retry (não são bugs de lógica)
_RETRY_ERRORS = ('disk i/o error', 'database is locked', 'unable to open',
                 'database disk image is malformed', 'sqlite_busy', 'sqlite_ioerr')

_init_lock = threading.Lock()


def _is_transient(exc):
    s = str(exc).lower()
    return any(k in s for k in _RETRY_ERRORS)


def get_db(db_path, retries=3, base_delay=0.4):
    """
    Abre conexão SQLite com todas as PRAGMAs de robustez.
    Faz retry automático em erros transientes (disk I/O, locked).
    """
    last_exc = None
    for attempt in range(retries):
        try:
            conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")   # 30 s de retry interno SQLite
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-8000")     # 8 MB page cache
            conn.execute("PRAGMA temp_store=MEMORY")    # tabelas temp em RAM
            conn.execute("PRAGMA mmap_size=67108864")   # 64 MB mmap
            return conn
        except sqlite3.DatabaseError as e:
            last_exc = e
            if _is_transient(e) and attempt < retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"DB open transient error (attempt {attempt+1}): {e} — retry {delay:.1f}s")
                time.sleep(delay)
            else:
                raise
    raise last_exc  # type: ignore


def safe_close(conn):
    """Fecha conexão silenciosamente."""
    try:
        if conn:
            conn.close()
    except Exception as e:
        logger.debug(f"safe_close: {e}")


def run_with_retry(db_path, fn, retries=3, base_delay=0.4):
    """
    Executa fn(conn) com retry completo (reabre DB em cada tentativa).
    Usa-se para operações críticas onde disk I/O pode ser transiente.
    """
    last_exc = None
    for attempt in range(retries):
        conn = None
        try:
            conn = get_db(db_path)
            result = fn(conn)
            return result
        except sqlite3.DatabaseError as e:
            last_exc = e
            if _is_transient(e) and attempt < retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"DB run_with_retry (attempt {attempt+1}): {e} — retry {delay:.1f}s")
                time.sleep(delay)
            else:
                raise
        finally:
            safe_close(conn)
    raise last_exc  # type: ignore


def check_integrity(db_path):
    """
    Verifica integridade da base de dados.
    Retorna (ok: bool, detail: str).
    """
    try:
        conn = get_db(db_path)
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
            detail = ', '.join(r[0] for r in rows)
            ok = (detail.strip().lower() == 'ok')
            return ok, detail
        finally:
            safe_close(conn)
    except Exception as e:
        return False, str(e)


def repair_db(db_path):
    """
    Tenta reparar DB corrupta via VACUUM INTO.
    Se falhar, faz backup e recria do zero.
    Retorna (ok: bool, message: str).
    """
    backup_path = db_path + '.bak'
    repaired_path = db_path + '.repaired'
    logger.warning(f"DB repair iniciado: {db_path}")

    # 1. Tenta VACUUM INTO para copia limpa
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute(f"VACUUM INTO '{repaired_path}'")
        conn.close()
        shutil.move(db_path, backup_path)
        shutil.move(repaired_path, db_path)
        logger.info("DB reparada via VACUUM INTO")
        return True, "reparada via VACUUM"
    except Exception as e:
        logger.warning(f"VACUUM INTO falhou: {e}")

    # 2. Faz backup e recria do zero
    try:
        if os.path.exists(db_path):
            shutil.copy2(db_path, backup_path)
            os.remove(db_path)
        for ext in ('-wal', '-shm'):
            p = db_path + ext
            if os.path.exists(p):
                os.remove(p)
        logger.warning("DB corrompida removida — será recriada pelo init_db")
        return True, "recriada do zero (backup em .bak)"
    except Exception as e:
        logger.error(f"DB repair falhou: {e}")
        return False, str(e)


def checkpoint_wal(db_path):
    """Força WAL checkpoint para liberar ficheiros -wal e -shm."""
    try:
        conn = get_db(db_path)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.commit()
        finally:
            safe_close(conn)
    except Exception as e:
        logger.debug(f"WAL checkpoint: {e}")


def ensure_healthy(db_path):
    """
    Verifica saúde da DB ao arranque.
    Se estiver corrompida, repara e reinicializa.
    Retorna (ok: bool, message: str).
    """
    with _init_lock:
        # Checkpoint WAL para limpar ficheiros pendentes
        checkpoint_wal(db_path)

        ok, detail = check_integrity(db_path)
        if ok:
            return True, "ok"

        logger.error(f"DB integrity_check falhou: {detail} — a reparar...")
        repaired, msg = repair_db(db_path)
        if repaired:
            # reinicia esquema
            try:
                init_db(db_path)
                return True, f"reparada e reinicializada ({msg})"
            except Exception as e:
                return False, f"repair ok mas init falhou: {e}"
        return False, f"repair falhou: {msg}"


def init_db(db_path):
    import os
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

    admin_pass = os.environ.get('ADMIN_PASSWORD', 'nexus2024')
    pw_hash = hashlib.sha256(admin_pass.encode()).hexdigest()
    try:
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ('admin', pw_hash))
        db.commit()
    except Exception:
        pass
    safe_close(db)
