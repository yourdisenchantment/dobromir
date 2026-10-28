"""deploy/deploy.sh на временных репозиториях, как на сервере (решено 2026-10-28).

Настоящие git, bash и deploy/locked.py; вместо uv, npm и `python -m pipeline` - заглушки,
которые записывают вызовы. Флаги в репозитории (`FAIL_BUILD`, `FAIL_MIGRATE`) заставляют
заглушку упасть на нужном шаге. Окружение - почти пустое, как у cron.
"""

import fcntl
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

STUB_PY = """#!/bin/sh
[ "$1" = "-c" ] && exit 0
shift 2
echo "$1 lock=$DOBROMIR_LOCK_HELD check=$CONTENT_CHECK_ONLY" >> "$DOBROMIR_DATA/calls"
case "$1" in
build)
    if [ -f ../FAIL_BUILD ]; then echo "Релиз не собран, сайт не тронут: проверка не прошла" >&2; exit 1; fi
    n=$(git rev-parse --short HEAD)
    echo "Релиз r-$n собран и проверен, public_html не тронут."
    echo "Включить: py -m pipeline rollback --to r-$n" ;;
migrate)
    if [ -f ../FAIL_MIGRATE ]; then echo "миграция упала" >&2; exit 1; fi
    echo "схема базы: версия 2, без изменений" ;;
rollback) echo "$3" > "$DOBROMIR_DATA/current" ;;
esac
"""
STUB_TOOL = """#!/bin/sh
echo "$(basename "$0") $*" >> "$DOBROMIR_DATA/calls"
"""


def sh(*cmd: str, cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def git(cwd: Path, *args: str) -> str:
    return sh("git", "-c", "user.name=t", "-c", "user.email=t@t", *args, cwd=cwd)


def stub(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


class Server:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.home = tmp / "home"
        self.data = tmp / "data"
        self.dev = tmp / "dev"
        self.clone = tmp / "server"
        origin = tmp / "origin.git"
        sh("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp)
        self.dev.mkdir()
        git(self.dev, "init", "-q", "-b", "main")
        shutil.copytree(ROOT / "deploy", self.dev / "deploy")
        (self.dev / ".gitignore").write_text(".venv/\nnode_modules/\n", encoding="utf-8")
        for name in ("pipeline/uv.lock", "site/package-lock.json"):
            (self.dev / name).parent.mkdir(parents=True, exist_ok=True)
            (self.dev / name).write_text("1\n", encoding="utf-8")
        self.commit("начало")
        git(self.dev, "remote", "add", "origin", str(origin))
        git(self.dev, "push", "-q", "origin", "main")
        sh("git", "clone", "-q", str(origin), str(self.clone), cwd=tmp)
        stub(self.clone / "pipeline/.venv/bin/python", STUB_PY)
        (self.clone / "site/node_modules").mkdir(parents=True)
        (self.clone / "site/node_modules/.package-lock.json").write_text("{}", encoding="utf-8")
        stub(self.home / ".local/share/dobromir-uv/bin/uv", STUB_TOOL)
        stub(self.tmp / "node/bin/npm", STUB_TOOL)
        (self.data / "export").mkdir(parents=True)
        (self.data / "export/news.json").write_text("{}", encoding="utf-8")
        (self.data / "db").mkdir()
        (self.data / "db/dobromir.sqlite").write_text("", encoding="utf-8")

    def commit(self, message: str, **files: str) -> str:
        for name, text in files.items():
            path = self.dev / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.dev, "rev-parse", "HEAD")

    def push(self, message: str, **files: str) -> str:
        sha = self.commit(message, **files)
        git(self.dev, "push", "-q", "-f", "origin", "HEAD:main")
        return sha

    def drop(self, name: str) -> str:
        git(self.dev, "rm", "-q", name)
        git(self.dev, "commit", "-q", "-m", f"убрать {name}")
        git(self.dev, "push", "-q", "origin", "main")
        return git(self.dev, "rev-parse", "HEAD")

    def deploy(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            "HOME": str(self.home),
            "PATH": os.environ["PATH"],  # git и bash; сам скрипт ставит свой PATH
            "DOBROMIR_DATA": str(self.data),
            "NODE_BIN": str(self.tmp / "node/bin"),
            "PYTHON": sys.executable,
        }
        return subprocess.run(
            ["bash", str(self.clone / "deploy/deploy.sh"), *args],
            cwd=self.clone,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    @property
    def head(self) -> str:
        return git(self.clone, "rev-parse", "HEAD")

    @property
    def current(self) -> str | None:
        path = self.data / "current"
        return path.read_text(encoding="utf-8").strip() if path.exists() else None

    def calls(self) -> list[str]:
        path = self.data / "calls"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


@pytest.fixture
def server(tmp_path: Path) -> Server:
    if shutil.which("bash") is None or shutil.which("git") is None:
        pytest.skip("нужны bash и git")
    return Server(tmp_path)


def test_cron_without_news_is_silent(server: Server) -> None:
    r = server.deploy("--cron")
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    assert server.calls() == []


def test_new_commit_is_built_checked_switched_and_reported(server: Server) -> None:
    sha = server.push("feat: новый раздел")
    r = server.deploy("--cron")
    assert r.returncode == 0, r.stderr
    assert r.stderr == ""
    assert "Сайт обновлен" in r.stdout and "feat: новый раздел" in r.stdout
    assert server.head == sha
    assert server.current == f"r-{sha[:7]}"
    # Порядок: сборка до миграций, включение - последним; все под блокировкой деплоя,
    # сборка - в режиме проверки содержимого.
    steps = [c.split()[0] for c in server.calls() if not c.startswith(("uv", "npm"))]
    assert steps == ["build", "backup", "migrate", "rollback"]
    assert all("lock=1" in c and "check=1" in c for c in server.calls() if not c.startswith(("uv", "npm")))
    assert "npm ci" not in "\n".join(server.calls())  # lock не менялся
    assert "Сайт обновлен" in (server.data / "logs/deploy.log").read_text(encoding="utf-8")


def test_new_package_lock_runs_npm_ci(server: Server) -> None:
    server.push("build(site): обновить зависимости", **{"site/package-lock.json": "2\n"})
    assert server.deploy("--cron").returncode == 0
    assert "npm ci --no-fund --no-audit" in server.calls()


def test_build_failure_keeps_site_reverts_code_and_reports(server: Server) -> None:
    old = server.head
    server.deploy("--cron")
    bad = server.push("fix: сломанное", FAIL_BUILD="1", **{"site/package-lock.json": "2\n"})
    r = server.deploy("--cron")
    assert r.returncode == 1
    assert r.stdout == ""
    assert "ошибка на шаге «сборка»" in r.stderr and "прежнем релизе" in r.stderr
    assert "проверка не прошла" in r.stderr  # причина - из журнала
    assert "возвращены" in r.stderr
    assert server.head == old
    assert git(server.clone, "symbolic-ref", "--short", "HEAD") == "main"
    assert server.current is None  # не переключали
    assert "migrate" not in " ".join(server.calls())  # до миграций не дошли
    assert (server.data / "deploy-state").read_text(encoding="utf-8") == f"failed={bad}\n"
    # Зависимости вернули к прежнему lock: npm ci второй раз - уже для старого.
    assert server.calls().count("npm ci --no-fund --no-audit") == 2


def test_failed_commit_not_retried_by_cron_but_retried_by_hand(server: Server) -> None:
    server.push("fix: сломанное", FAIL_BUILD="1")
    assert server.deploy("--cron").returncode == 1
    again = server.deploy("--cron")
    assert (again.returncode, again.stdout, again.stderr) == (0, "", "")
    assert server.deploy().returncode == 1  # руками - пробует


def test_fix_after_failure_goes_out(server: Server) -> None:
    server.push("fix: сломанное", FAIL_BUILD="1")
    server.deploy("--cron")
    good = server.drop("FAIL_BUILD")
    r = server.deploy("--cron")
    assert r.returncode == 0, r.stderr
    assert server.head == good and server.current == f"r-{good[:7]}"
    assert (server.data / "deploy-state").read_text(encoding="utf-8") == "failed=\n"


def test_migration_failure_keeps_new_code_and_old_site(server: Server) -> None:
    new = server.push("feat: новая схема", FAIL_MIGRATE="1")
    r = server.deploy("--cron")
    assert r.returncode == 1
    assert "«миграции»" in r.stderr and "код оставлен" in r.stderr and "backup" in r.stderr
    assert server.head == new
    assert server.current is None


def test_dirty_clone_refused_before_anything(server: Server) -> None:
    server.push("feat: новое")
    old = server.head
    (server.clone / "pipeline/uv.lock").write_text("правка на сервере\n", encoding="utf-8")
    r = server.deploy("--cron")
    assert r.returncode == 1 and "изменены файлы" in r.stderr
    assert server.head == old and server.calls() == []


def test_rewritten_history_refused(server: Server) -> None:
    server.push("feat: раз")
    server.deploy("--cron")
    git(server.dev, "reset", "-q", "--hard", "HEAD~1")
    server.push("feat: два, поверх переписанной истории")
    old = server.head
    r = server.deploy("--cron")
    assert r.returncode == 1 and "переписали" in r.stderr
    assert server.head == old


def test_pin_with_to_holds_cron_until_manual_run(server: Server) -> None:
    first = server.head
    server.push("feat: раз")
    server.deploy("--cron")
    r = server.deploy("--to", first)
    assert r.returncode == 0, r.stderr
    assert server.head == first and "откат" in r.stdout
    server.push("feat: два")
    quiet = server.deploy("--cron")
    assert (quiet.returncode, quiet.stdout, quiet.stderr) == (0, "", "")
    assert server.head == first  # закреплен
    back = server.deploy()
    assert back.returncode == 0, back.stderr
    assert server.head == git(server.dev, "rev-parse", "HEAD")
    assert git(server.clone, "symbolic-ref", "--short", "HEAD") == "main"


def test_manual_without_news_says_so(server: Server) -> None:
    r = server.deploy()
    assert r.returncode == 0 and "Новых изменений нет" in r.stdout


def test_no_switch_builds_but_does_not_switch(server: Server) -> None:
    server.push("feat: новое")
    r = server.deploy("--no-switch")
    assert r.returncode == 0, r.stderr
    assert "не включен" in r.stdout and server.current is None


def test_busy_lock_cron_silent_manual_explains(server: Server) -> None:
    server.push("feat: новое")
    old = server.head
    with open(server.data / "worker.lock", "a") as fh:
        fcntl.lockf(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        quiet = server.deploy("--cron")
        loud = server.deploy()
    assert (quiet.returncode, quiet.stdout, quiet.stderr) == (0, "", "")
    assert loud.returncode == 1 and "воркер" in loud.stderr
    assert server.head == old


def test_scripts_brace_variables_before_non_ascii() -> None:
    # В cron локаль C: bash считает байты кириллицы и «» частью имени, и «$STAGE»
    # превращается в неизвестную переменную - скрипт падает молча (найдено 2026-10-28).
    bad = [
        f"{path.name}:{n}"
        for path in sorted((ROOT / "deploy").glob("*.sh"))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]", line)
    ]
    assert bad == [], "писать ${VAR} перед не-ASCII: " + ", ".join(bad)
