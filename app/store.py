"""Local SQLite persistence. Callers serialize a session's mutations with its lock."""
import json
import sqlite3
import threading
from pathlib import Path


class Store:
    def __init__(self, path):
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.RLock()
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, session_id TEXT, body TEXT NOT NULL)')

    def save(self, session):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)',
                            (session['id'], json.dumps(session, ensure_ascii=False)))

    def get(self, key):
        with self.lock:
            row = self.db.execute('SELECT body FROM sessions WHERE id=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def event(self, key, event):
        with self.lock, self.db:
            self.db.execute('INSERT INTO events(session_id, body) VALUES (?, ?)',
                            (key, json.dumps(event, ensure_ascii=False)))

    def close(self):
        self.db.close()
