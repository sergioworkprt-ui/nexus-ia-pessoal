"""Notifications module."""
import logging
logger = logging.getLogger('nexus.notify')

def notify(user_id, title, body, db_path):
    try:
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute(
            "INSERT INTO notifications (user_id, title, body) VALUES (?, ?, ?)",
            (user_id, title, body)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Notify error: {e}")
