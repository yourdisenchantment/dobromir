"""Ключ-значение в SQLite: где остановились."""

import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self._db.commit()

    def get(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set(self, key: str, value: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, value))
        self._db.commit()

    def close(self) -> None:
        self._db.close()
