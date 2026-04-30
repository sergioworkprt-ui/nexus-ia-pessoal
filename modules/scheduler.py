"""Scheduler — fila de tarefas assíncronas com suporte a 24/7."""
import threading, datetime, json, logging, time

logger = logging.getLogger('nexus.scheduler')

class Scheduler:
    def __init__(self):
        self._running = False
        self._thread = None
        self._db_path = None
        self._ai_fn = None
        self._email_fn = None

    def start(self, db_path, ai_fn, email_fn):
        self._db_path = db_path
        self._ai_fn = ai_fn
        self._email_fn = email_fn
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler iniciado")

    def is_running(self):
        return self._running and self._thread and self._thread.is_alive()

    def _loop(self):
        while self._running:
            try:
                self.check_and_run()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            time.sleep(60)  # verifica a cada minuto

    def check_and_run(self):
        if not self._db_path: return
        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            now = datetime.datetime.now().isoformat()
            tasks = conn.execute(
                "SELECT * FROM tasks WHERE status='scheduled' AND run_at <= ?", (now,)
            ).fetchall()
            for task in tasks:
                self._execute_task(task, conn)
            conn.close()
        except Exception as e:
            logger.error(f"check_and_run error: {e}")

    def _execute_task(self, task, conn):
        try:
            desc = json.loads(task['description'] or '{}')
            prompt = desc.get('prompt', task['title'])
            logger.info(f"Executando tarefa: {task['title']}")

            messages = [{'role': 'user', 'content': prompt}]
            response, model = self._ai_fn(messages, '')

            conn.execute(
                "UPDATE tasks SET status='done', result=?, updated_at=datetime('now') WHERE id=?",
                (response[:1000], task['id'])
            )
            conn.commit()

            # Notifica por email
            email = task['email'] if hasattr(task, 'keys') and 'email' in task.keys() else ''
            if not email:
                email = desc.get('email', '')
            if email and self._email_fn:
                try:
                    self._email_fn(email, f"✅ Tarefa concluída: {task['title']}", response)
                except Exception as e:
                    logger.error(f"Email error: {e}")

            logger.info(f"Tarefa concluída: {task['title']} [{model}]")
        except Exception as e:
            logger.error(f"Execute task error: {e}")
            try:
                conn.execute(
                    "UPDATE tasks SET status='error', result=? WHERE id=?",
                    (str(e)[:200], task['id'])
                )
                conn.commit()
            except Exception:
                pass

    def add(self, user_id, title, prompt, run_at, email='', db_path=None):
        if not title or not prompt or not run_at:
            return {'error': 'title, prompt e run_at obrigatórios'}
        try:
            import sqlite3
            conn = sqlite3.connect(db_path or self._db_path)
            desc = json.dumps({'prompt': prompt, 'email': email})
            conn.execute(
                "INSERT INTO tasks (user_id, title, description, status, run_at, email) VALUES (?, ?, ?, 'scheduled', ?, ?)",
                (user_id, title, desc, run_at, email)
            )
            conn.commit()
            conn.close()
            logger.info(f"Tarefa agendada: {title} para {run_at}")
            return {'ok': True, 'message': f'Tarefa "{title}" agendada para {run_at}'}
        except Exception as e:
            return {'error': str(e)}

    def list_tasks(self, user_id):
        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tasks WHERE user_id=? AND status='scheduled' ORDER BY run_at",
                (user_id,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

scheduler = Scheduler()
