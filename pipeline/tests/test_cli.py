"""Команды для deploy.sh и cron отдельными процессами: коды выхода, вывод, блокировка."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

HOLD_LOCK = (
    "import fcntl, sys, time\n"
    "f = open(sys.argv[1], 'a')\n"
    "fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "print('locked', flush=True)\n"
    "time.sleep(60)\n"
)


def cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "DOBROMIR_DATA": str(tmp_path / "data"),
        "SITE_ROOT": str(tmp_path / "site"),
        "SITE_ENV": "staging",
    }
    return subprocess.run(
        [sys.executable, "-m", "pipeline", *args], env=env, capture_output=True, text=True, timeout=60, check=False
    )


def test_migrate_creates_then_reports_no_change(tmp_path: Path) -> None:
    first = cli(tmp_path, "migrate")
    assert first.returncode == 0 and "версия 0 -> " in first.stdout
    second = cli(tmp_path, "migrate")
    assert second.returncode == 0 and "без изменений" in second.stdout


def test_backup_command(tmp_path: Path) -> None:
    no_db = cli(tmp_path, "backup")
    assert no_db.returncode == 1 and "Копия базы не сделана" in no_db.stderr and no_db.stdout == ""
    cli(tmp_path, "migrate")
    ok = cli(tmp_path, "backup")
    assert ok.returncode == 0 and ok.stderr == "" and "dobromir-" in ok.stdout


@pytest.mark.parametrize("command", ["migrate", "build"])
def test_refuses_while_worker_runs(tmp_path: Path, command: str) -> None:
    (tmp_path / "data").mkdir()
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_LOCK, str(tmp_path / "data" / "worker.lock")], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "locked"
        r = cli(tmp_path, command)
        assert r.returncode == 1 and "Воркер сейчас работает" in r.stderr
    finally:
        holder.kill()
        holder.wait()
        if holder.stdout:
            holder.stdout.close()
    assert not (tmp_path / "data" / "db").exists()  # ничего не начато


def test_build_without_news_json_is_clear_error(tmp_path: Path) -> None:
    r = cli(tmp_path, "build")
    assert r.returncode == 1 and "Релиз не собран, сайт не тронут" in r.stderr and "export" in r.stderr
    assert not (tmp_path / "site" / "public_html").exists()


@pytest.mark.parametrize("command", ["migrate", "backup", "build", "rollback"])
def test_bad_settings_one_line_not_traceback(tmp_path: Path, command: str) -> None:
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "DOBROMIR_DATA": str(tmp_path / "data")}
    r = subprocess.run(
        [sys.executable, "-m", "pipeline", command], env=env, capture_output=True, text=True, timeout=60, check=False
    )
    assert r.returncode == 1 and "Неверные настройки" in r.stderr and "Traceback" not in r.stderr
