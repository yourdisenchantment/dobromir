"""Открытие SQLite и применение миграций из `store/migrations/NNNN_*.sql`."""

import re
import sqlite3
from importlib import resources
from pathlib import Path

MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def migrations() -> list[tuple[int, str]]:
    """Номер и текст каждой миграции, по возрастанию номера."""
    found: list[tuple[int, str]] = []
    for entry in resources.files("pipeline.store.migrations").iterdir():
        match = MIGRATION_NAME.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.read_text(encoding="utf-8")))
    found.sort()
    numbers = [n for n, _ in found]
    if numbers != list(range(1, len(numbers) + 1)):
        raise RuntimeError(f"миграции должны идти подряд с 0001, найдены номера {numbers}")
    return found


def schema_version(conn: sqlite3.Connection) -> int:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def migrate(conn: sqlite3.Connection) -> int:
    """Применяет недостающие миграции, каждую в своей транзакции. Возвращает итоговую версию."""
    current = schema_version(conn)
    conn.commit()
    for number, sql in migrations():
        if number <= current:
            continue
        # Явная транзакция: модуль sqlite3 сам открывает ее только перед INSERT/UPDATE, а CREATE
        # TABLE без нее фиксировался бы сразу - и упавшая миграция оставила бы половину схемы.
        saved = conn.isolation_level
        conn.isolation_level = None
        try:
            conn.execute("BEGIN")
            for statement in _statements(sql):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (number,))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.isolation_level = saved
        current = number
    return current


def _statements(sql: str) -> list[str]:
    """Делит файл на команды по `;`, убрав комментарии `--`. В миграциях не писать `;` и `--` внутри строк."""
    lines = [line.split("--", 1)[0] for line in sql.splitlines()]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def open_db(path: Path) -> sqlite3.Connection:
    """Открывает базу (создает каталог при надобности) и доводит схему до последней версии."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    migrate(conn)
    return conn
