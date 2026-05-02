from modules.database import get_db
"""Reporter — gera relatórios automáticos."""
import os, datetime, json

def generate(user_id, report_type, db_path, data_dir, ai_fn):
    try:
        import sqlite3
        conn = get_db(db_path)
        conn.row_factory = sqlite3.Row

        if report_type == 'daily':
            since = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat()
        elif report_type == 'weekly':
            since = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
        else:
            since = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat()

        msgs = conn.execute(
            "SELECT COUNT(*) as c FROM conversations WHERE user_id=? AND created_at > ?",
            (user_id, since)
        ).fetchone()['c']

        tasks_done = conn.execute(
            "SELECT COUNT(*) as c FROM tasks WHERE user_id=? AND status='done' AND updated_at > ?",
            (user_id, since)
        ).fetchone()['c']

        usage = conn.execute(
            "SELECT provider, COUNT(*) as calls FROM ai_usage WHERE user_id=? AND created_at > ? GROUP BY provider",
            (user_id, since)
        ).fetchall()
        conn.close()

        usage_str = ', '.join([f"{r['provider']}: {r['calls']} calls" for r in usage])
        prompt = f"""Cria um relatório {report_type} da NEXUS:
- Mensagens trocadas: {msgs}
- Tarefas concluídas: {tasks_done}
- IAs usadas: {usage_str}

Resume a atividade e sugere melhorias para o próximo período."""

        messages = [{'role': 'user', 'content': prompt}]
        response, model = ai_fn(messages, '')

        # Guarda relatório
        report_dir = os.path.join(data_dir, 'reports')
        os.makedirs(report_dir, exist_ok=True)
        filename = f"report_{report_type}_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.txt"
        with open(os.path.join(report_dir, filename), 'w') as f:
            f.write(response)

        return {'ok': True, 'report': response, 'model': model, 'file': filename}
    except Exception as e:
        return {'error': str(e)[:200]}
