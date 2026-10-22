"""Воркер для cron: блокировка, коды выхода, письмо, status.json, лог."""

import io
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from fakevk import FakeWall
from pipeline.settings import Settings, load_settings
from pipeline.store import Store, open_db
from pipeline.worker import (
    EXIT_ERROR,
    EXIT_MASS_DELETE,
    EXIT_OK,
    EXIT_VK_KEY,
    file_logging,
    log,
    run_worker,
)

TZ = ZoneInfo("Europe/Simferopol")
HOLD_LOCK = (
    "import fcntl, sys, time\n"
    "f = open(sys.argv[1], 'a')\n"
    "fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "print('locked', flush=True)\n"
    "time.sleep(60)\n"
)
SECRET = "vk1.a.WORKER-SECRET-TOKEN"


def at(day: int, hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 10, day, hour, minute, tzinfo=TZ).timestamp())


def settings_at(tmp_path: Path, **extra: str) -> Settings:
    env = {
        "DOBROMIR_DATA": str(tmp_path / "data"),
        "SITE_ROOT": str(tmp_path / "site"),
        "SITE_ENV": "staging",
        "VK_SERVICE_TOKEN": SECRET,
        "VK_GROUP_ID": "49938199",
        "VK_WINDOW": "20",
        "VK_BY_ID_BATCH": "4",
        **extra,
    }
    return load_settings(env)


def run(s: Settings, wall: FakeWall, now: int, **kw):  # type: ignore[no-untyped-def]
    err = io.StringIO()
    code = run_worker(s, wall.http(), now=now, stderr=err, **kw)
    return code, err.getvalue()


def status(s: Settings) -> dict:  # type: ignore[type-arg]
    return json.loads(s.data.status_json.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_success_is_silent_and_writes_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    s = settings_at(tmp_path)
    code, err = run(s, FakeWall(5), at(23, 1))
    assert code == EXIT_OK and err == ""
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""  # cron не пришлет письмо
    st = status(s)
    assert st["posts_total"] == 5 and st["posts_deleted"] == 0
    assert st["pending"] is True and st["last_error"] is None
    assert st["last_ok_poll_at"] and st["worker_version"]
    assert st["builds_today"] == 0 and st["max_builds_per_day"] == 4
    assert "посты:" in s.data.worker_log.read_text(encoding="utf-8")


def test_second_run_while_first_holds_lock_exits_0_and_touches_nothing(tmp_path: Path) -> None:
    """fcntl-блокировка - между процессами (внутри одного процесса повторная проходит),
    поэтому «первый запуск» здесь - настоящий отдельный процесс, как в cron."""
    s = settings_at(tmp_path)
    s.data.root.mkdir(parents=True)
    wall = FakeWall(5)
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_LOCK, str(s.data.lock_file)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "locked"
        code, err = run(s, wall, at(23, 1))
    finally:
        holder.kill()
        holder.wait()
        if holder.stdout is not None:
            holder.stdout.close()
    assert code == EXIT_OK and err == ""
    assert wall.calls == []  # в VK не ходил
    assert not s.data.db.exists() and not s.data.status_json.exists()
    assert "предыдущий запуск не закончен" in s.data.worker_log.read_text(encoding="utf-8")


def test_lock_released_after_run(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    run(s, FakeWall(3), at(23, 1))
    probe = subprocess.run(
        [sys.executable, "-c", HOLD_LOCK.replace("time.sleep(60)", "pass"), str(s.data.lock_file)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert probe.returncode == 0 and probe.stdout.strip() == "locked"  # другой процесс смог взять


def test_vk_key_error_exit_2_with_clear_message(tmp_path: Path) -> None:
    s = settings_at(tmp_path)

    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"error_code": 5, "error_msg": f"invalid token {SECRET}"}})

    err = io.StringIO()
    code = run_worker(s, httpx.Client(transport=httpx.MockTransport(denied)), now=at(23, 1), stderr=err)
    assert code == EXIT_VK_KEY
    text = err.getvalue()
    assert "ключ VK не принят" in text and "обратитесь к разработчику" in text
    assert len(text.strip().splitlines()) <= 2
    for content in (
        text,
        s.data.status_json.read_text(encoding="utf-8"),
        s.data.worker_log.read_text(encoding="utf-8"),
    ):
        assert SECRET not in content
    assert status(s)["last_error"]["code"] == EXIT_VK_KEY


def test_mass_deletion_exit_3(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    wall = FakeWall(10)
    run(s, wall, at(23, 1))
    for i in (1, 2, 3, 4):
        wall.delete(i)
    code, err = run(s, wall, at(23, 4))
    assert code == EXIT_MASS_DELETE and "удаление остановлено" in err
    st = status(s)
    assert st["posts_total"] == 10 and st["posts_deleted"] == 0  # база не тронута


def test_vk_internal_error_exit_1(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    wall = FakeWall(3)
    wall.fail_methods.add("wall.get")
    code, err = run(s, wall, at(23, 1))
    assert code == EXIT_ERROR and "Новости не обновлены" in err


def test_network_error_exit_1(tmp_path: Path) -> None:
    s = settings_at(tmp_path)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети")

    err = io.StringIO()
    from pipeline.vk import client as vkclient

    original = vkclient.RETRY_PAUSES
    vkclient.RETRY_PAUSES = (0.0, 0.0, 0.0)
    try:
        code = run_worker(s, httpx.Client(transport=httpx.MockTransport(down)), now=at(23, 1), stderr=err)
    finally:
        vkclient.RETRY_PAUSES = original
    assert code == EXIT_ERROR and "VK временно недоступен" in err.getvalue()


def test_failure_keeps_last_ok_and_history(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    wall = FakeWall(3)
    run(s, wall, at(23, 1))
    ok_at = status(s)["last_ok_poll_at"]
    wall.fail_methods.add("wall.get")
    run(s, wall, at(23, 2))
    run(s, wall, at(23, 3))
    st = status(s)
    assert st["last_ok_poll_at"] == ok_at  # время последнего успеха не затерто
    assert len(st["errors"]) == 2 and st["last_error"]["code"] == EXIT_ERROR
    wall.fail_methods.clear()
    run(s, wall, at(23, 4))
    assert status(s)["last_error"] is None


def test_missing_key_is_error_not_crash(tmp_path: Path) -> None:
    s = load_settings(
        {
            "DOBROMIR_DATA": str(tmp_path / "data"),
            "SITE_ROOT": str(tmp_path / "site"),
            "SITE_ENV": "staging",
            "VK_GROUP_ID": "1",
        }
    )
    code, err = run(s, FakeWall(1), at(23, 1))
    assert code == EXIT_ERROR and "VK_SERVICE_TOKEN" in err


def test_build_hook_called_and_recorded(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    builds: list[int] = []
    code, _ = run(s, FakeWall(3), at(23, 1), build=lambda settings, now: builds.append(now))
    assert code == EXIT_OK and builds == [at(23, 1)]
    st = status(s)
    assert st["pending"] is False and st["builds_today"] == 1 and st["last_build_at"]


def test_failed_build_keeps_pending(tmp_path: Path) -> None:
    s = settings_at(tmp_path)

    def broken(settings: Settings, now: int) -> None:
        raise RuntimeError("astro build упал")

    code, err = run(s, FakeWall(3), at(23, 1), build=broken)
    assert code == EXIT_ERROR and "astro build упал" in err
    st = status(s)
    assert st["pending"] is True and st["builds_today"] == 0
    store = Store(open_db(s.data.db))
    assert store.counts() == (3, 0)  # данные синка сохранились, собрать можно позже
    store.close()


def test_log_rotation(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    with file_logging(s, max_bytes=2000):
        for i in range(200):
            log.info("строка %s %s", i, "x" * 50)
    files = sorted(p.name for p in s.data.worker_log.parent.iterdir())
    assert files == ["worker.log", "worker.log.1", "worker.log.2", "worker.log.3", "worker.log.4", "worker.log.5"]
    assert not log.handlers and logging.getLogger("pipeline").propagate is True


def test_status_has_no_secrets(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    run(s, FakeWall(3), at(23, 1))
    text = s.data.status_json.read_text(encoding="utf-8")
    assert SECRET not in text and "token" not in text.lower()
    assert not list(s.data.root.glob("*.tmp"))
