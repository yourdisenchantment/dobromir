"""Копия базы SQLite в `<данные>/backup/`, хранится 7 последних.

Копирует встроенный механизм SQLite (`Connection.backup`, то же, что `sqlite3 .backup`):
согласованный снимок даже при записи воркером, без утилиты `sqlite3` на сервере. Копия
проверяется `PRAGMA integrity_check` и только потом получает свое имя: недописанный файл
никогда не выглядит готовой копией.
"""

import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from pipeline.settings import Settings

log = logging.getLogger("pipeline")

BACKUP_NAME = re.compile(r"^dobromir-(\d{8}-\d{6})(?:-(\d+))?\.sqlite$")
KEEP_BACKUPS = 7


class BackupError(RuntimeError):
    """Копия не сделана; прежние копии не тронуты."""


def backups(directory: Path) -> list[Path]:
    """Копии по возрастанию времени. Только с нашим именем: чужие файлы не трогаем."""
    if not directory.is_dir():
        return []
    return sorted((p for p in directory.iterdir() if p.is_file() and BACKUP_NAME.match(p.name)), key=_order)


def _order(path: Path) -> tuple[str, int]:
    """Время, затем номер копии за ту же секунду. Не по имени: «-1.sqlite» встало бы раньше «.sqlite»."""
    match = BACKUP_NAME.match(path.name)
    assert match is not None  # backups() отбирает только такие имена
    return match.group(1), int(match.group(2) or 0)


def backup_db(settings: Settings, now: int, keep: int = KEEP_BACKUPS) -> Path:
    """Сделать копию, проверить ее, удалить лишние старые. Возвращает путь копии.

    Raises:
        BackupError: базы нет или копия не прошла проверку.
    """
    source = settings.data.db
    if not source.is_file():
        raise BackupError(f"нет базы {source}")
    target_dir = settings.data.backups
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    # За ту же секунду - номер больше всех занятых, даже если младшие уже вычищены:
    # иначе новая копия получила бы освободившееся «старое» имя и ушла бы первой в чистку.
    stamp = datetime.fromtimestamp(now, settings.tz).strftime("%Y%m%d-%H%M%S")
    taken = [n for s, n in map(_order, backups(target_dir)) if s == stamp]
    n = max(taken) + 1 if taken else 0
    target = target_dir / (f"dobromir-{stamp}-{n}.sqlite" if n else f"dobromir-{stamp}.sqlite")
    while target.exists():  # чужой файл с таким именем
        n += 1
        target = target_dir / f"dobromir-{stamp}-{n}.sqlite"
    part = target.with_name(target.name + ".part")
    try:
        # Только чтение: копия не должна применять миграции или что-то менять в базе.
        with (
            closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)) as src,
            closing(sqlite3.connect(part)) as dst,
        ):
            src.backup(dst)
        os.chmod(part, 0o600)  # в базе материалы о детях
        with closing(sqlite3.connect(part)) as check:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise BackupError(f"копия не прошла integrity_check: {result}")
        os.replace(part, target)
    except sqlite3.Error as exc:
        part.unlink(missing_ok=True)
        raise BackupError(f"SQLite: {exc}") from exc
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    found = backups(target_dir)
    removed = [old.name for old in found[: max(0, len(found) - keep)]]
    for name in removed:
        (target_dir / name).unlink()
    log.info("копия базы %s; удалены старые: %s", target.name, ", ".join(removed) or "нет")
    return target
