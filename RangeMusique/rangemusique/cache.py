"""Cache SQLite : évite de refaire les empreintes et les requêtes internet.

Grâce à lui, une analyse interrompue reprend presque instantanément là où
elle s'était arrêtée.
"""

import json
import sqlite3
import threading


class Cache:
    def __init__(self, path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS kv (ns TEXT, k TEXT, v TEXT, PRIMARY KEY (ns, k))"
        )
        self._db.commit()

    def get(self, ns, key):
        with self._lock:
            row = self._db.execute(
                "SELECT v FROM kv WHERE ns=? AND k=?", (ns, key)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, ns, key, value):
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO kv (ns, k, v) VALUES (?, ?, ?)",
                (ns, key, json.dumps(value)),
            )
            self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()


class MemoryCache(Cache):
    def __init__(self):
        super().__init__(":memory:")
