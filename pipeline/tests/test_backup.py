"""Копия базы: снимок, проверка, 7 последних, чужие файлы, права, ошибки."""

import os
import sqlite3
import stat
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pipeline.backup import BackupError, backup_db, backups
from pipeline.settings import Settings, load_settings
from pipeline.store import open_db

TZ = ZoneInfo("Europe/Simferopol")


def at(day: int, hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 10, day, hour, minute, tzinfo=TZ).timestamp())


def settings_at(tmp_path: Path) -> Settings:
    return load_settings(
        {"DOBROMIR_DATA": str(tmp_path / "data"), "SITE_ROOT": str(tmp_path / "site"), "SITE_ENV": "staging"}
    )


def with_db(tmp_path: Path) -> Settings:
    s = settings_at(tmp_path)
    with closing(open_db(s.data.db)) as conn:
        conn.execute("INSERT INTO meta (key, value) VALUES ('probe', 'добромир')")
        conn.commit()
    return s


def test_backup_is_a_full_readable_copy(tmp_path: Path) -> None:
    s = with_db(tmp_path)
    path = backup_db(s, at(24, 3, 47))
    assert path.name == "dobromir-20261024-034700.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'probe'").fetchone()[0] == "добромир"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600  # материалы о детях
    assert not list(s.data.backups.glob("*.part"))


def test_keeps_seven_and_ignores_foreign_files(tmp_path: Path) -> None:
    s = with_db(tmp_path)
    s.data.backups.mkdir(parents=True)
    (s.data.backups / "ручная-копия.sqlite").write_bytes(b"x")
    made = [backup_db(s, at(10 + i, 3)).name for i in range(9)]
    assert [p.name for p in backups(s.data.backups)] == made[-7:]
    assert (s.data.backups / "ручная-копия.sqlite").is_file()


def test_same_second_gets_distinct_name(tmp_path: Path) -> None:
    s = with_db(tmp_path)
    a, b = backup_db(s, at(24, 3)), backup_db(s, at(24, 3))
    assert a != b and b.name == "dobromir-20261024-030000-1.sqlite"


def test_same_second_copies_pruned_oldest_first(tmp_path: Path) -> None:
    """Найдено на прогоне скриптов: по имени «...-1.sqlite» меньше «....sqlite», чистка удаляла бы новые."""
    s = with_db(tmp_path)
    made = [backup_db(s, at(24, 3), keep=3).name for _ in range(5)]
    assert made[0] == "dobromir-20261024-030000.sqlite" and made[4] == "dobromir-20261024-030000-4.sqlite"
    assert [p.name for p in backups(s.data.backups)] == made[-3:]


def test_backup_does_not_touch_source(tmp_path: Path) -> None:
    s = with_db(tmp_path)
    before = s.data.db.read_bytes()
    backup_db(s, at(24, 3))
    assert s.data.db.read_bytes() == before


def test_no_db_is_error(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    with pytest.raises(BackupError, match="нет базы"):
        backup_db(s, at(24, 3))


def test_broken_db_is_error_and_old_copies_survive(tmp_path: Path) -> None:
    s = with_db(tmp_path)
    good = backup_db(s, at(24, 3))
    s.data.db.write_bytes(b"not a database at all" * 100)
    with pytest.raises(BackupError, match="SQLite"):
        backup_db(s, at(25, 3))
    assert backups(s.data.backups) == [good]
    assert not list(s.data.backups.glob("*.part"))
