"""Точка входа воркера для cron: `python -m pipeline worker`.

Правила (отчет о хостинге, разд. 6 и 9):
- без ошибок ничего не печатает - cron присылает письмо на любой вывод;
- при ошибке - 1-2 строки по-русски в stderr (уйдут письмом), подробности - в лог;
- каждый запуск записывает status.json (без секретов);
- второй запуск, пока идет первый, тихо выходит с кодом 0.

Коды выхода: 0 - успех, нет изменений или занята блокировка; 1 - прочая ошибка;
2 - ключ VK не принят; 3 - сработала защита от массового удаления.
"""

import fcntl
import json
import logging
import os
import sys
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from importlib import metadata
from logging.handlers import RotatingFileHandler
from typing import IO, Any

import httpx

from pipeline.builds import LAST_BUILD_AT, builds_today, pending_since, record_build
from pipeline.media.cleanup import cleanup_media
from pipeline.reconcile import SyncError
from pipeline.release import ReleaseError
from pipeline.run import SyncResult, run_sync
from pipeline.settings import Settings
from pipeline.store import Store, open_db
from pipeline.vk.client import VkAuthError, VkClient, VkNetworkError

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_VK_KEY = 2
EXIT_MASS_DELETE = 3

LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUPS = 5
STATUS_ERRORS_KEPT = 10

log = logging.getLogger("pipeline")

Build = Callable[[Settings, int], object]  # результат не используется


def worker_version() -> str:
    try:
        return metadata.version("dobromir-pipeline")
    except metadata.PackageNotFoundError:
        return "unknown"


@contextmanager
def file_logging(settings: Settings, max_bytes: int = LOG_MAX_BYTES) -> Iterator[None]:
    """Лог в `logs/worker.log` с ротацией (5 файлов по 1 МБ). Только в файл: вывод на экран - это письмо."""
    settings.data.worker_log.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        settings.data.worker_log, maxBytes=max_bytes, backupCount=LOG_BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    previous = log.level, log.propagate
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    try:
        yield
    finally:
        log.removeHandler(handler)
        handler.close()
        log.setLevel(previous[0])
        log.propagate = previous[1]


@contextmanager
def single_instance(settings: Settings) -> Iterator[bool]:
    """fcntl-блокировка на файле в каталоге данных (не shell-flock, требование отчета).

    Возвращает False, если другой запуск еще идет. Блокировку снимает ОС, даже если процесс упал.
    """
    settings.data.root.mkdir(parents=True, exist_ok=True)
    fh: IO[str] = open(settings.data.lock_file, "a")  # noqa: SIM115 - держим открытым до конца запуска
    try:
        try:
            fcntl.lockf(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.lockf(fh, fcntl.LOCK_UN)
    finally:
        fh.close()


def _iso(ts: int | None, settings: Settings) -> str | None:
    """Время в status.json - местное (его читает администратор хостинга), с поясом."""
    return None if ts is None else datetime.fromtimestamp(ts, settings.tz).isoformat()


def _scrub(text: str, settings: Settings) -> str:
    """Страховка: ключи не должны попасть ни в письмо, ни в статус, даже если пришли в тексте ошибки."""
    for secret in (settings.vk_service_token, settings.vk_community_token):
        if secret:
            text = text.replace(secret, "***")
    return text


def write_status(settings: Settings, status: dict[str, Any]) -> None:
    """Атомарная запись status.json."""
    path = settings.data.status_json
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_status(settings: Settings) -> dict[str, Any]:
    try:
        data = json.loads(settings.data.status_json.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _message(exc: BaseException) -> tuple[int, str]:
    """Код выхода и текст письма для человека без технической подготовки."""
    if isinstance(exc, VkAuthError):
        return EXIT_VK_KEY, (
            "Новости с сайта не обновляются: ключ VK не принят (истек или отозван).\n"
            "Нужен новый ключ - обратитесь к разработчику."
        )
    if isinstance(exc, SyncError):
        return EXIT_MASS_DELETE, (
            "Новости не обновлены: VK вернул слишком мало постов, удаление остановлено ради сохранности.\n"
            f"Сайт работает со старыми данными. Подробности: {exc}"
        )
    if isinstance(exc, ReleaseError):
        return EXIT_ERROR, (
            "Сайт не пересобран, он работает на прежней версии; новости обновятся при следующей удачной сборке.\n"
            f"Причина: {exc}"
        )
    if isinstance(exc, VkNetworkError):
        return EXIT_ERROR, (
            f"Новости не обновлены: VK временно недоступен. Следующий запуск попробует снова.\nПодробности: {exc}"
        )
    return EXIT_ERROR, f"Новости не обновлены из-за ошибки воркера: {type(exc).__name__}: {exc}"


def run_worker(
    settings: Settings,
    http: httpx.Client,
    now: int | None = None,
    build: Build | None = None,
    stderr: IO[str] | None = None,
) -> int:
    """Один запуск из cron. Возвращает код выхода."""
    err = sys.stderr if stderr is None else stderr
    now = int(time.time()) if now is None else now
    with file_logging(settings), single_instance(settings) as acquired:
        if not acquired:
            log.info("предыдущий запуск не закончен, этот пропущен")
            return EXIT_OK
        status = read_status(settings)
        status.update({"worker_version": worker_version(), "last_run_at": _iso(now, settings)})
        code = EXIT_OK
        store: Store | None = None
        try:
            store = Store(open_db(settings.data.db))
            result = run_sync(store, VkClient(settings.vk(), http), http, settings, now)
            _log_result(result)
            if result.build_now:
                if build is None:
                    log.info("сборка нужна, но сборщик еще не подключен (P1-6); изменения ждут")
                else:
                    build(settings, now)  # исключение - сборка не удалась, флаг остается
                    record_build(store, now, settings.tz)
                    log.info("сборка выполнена")
            if pending_since(store) is None:
                # Только на свежем сайте: текущий релиз собран без истекших постов, значит
                # их фото ему не нужны. Пока сборка не прошла, релиз может их еще показывать.
                cleanup_media(store, settings.site.media)
            status["last_ok_poll_at"] = _iso(now, settings)
            status["last_error"] = None
        except Exception as exc:  # воркер обязан превратить любую ошибку в код и письмо
            code, text = _message(exc)
            text = _scrub(text, settings)
            log.error("%s\n%s", text, _scrub(traceback.format_exc(), settings))
            print(text, file=err)
            entry = {"at": _iso(now, settings), "code": code, "message": text}
            status["last_error"] = entry
            status["errors"] = [entry, *(status.get("errors") or [])][:STATUS_ERRORS_KEPT]
        finally:
            if store is not None:
                _fill_counts(status, store, settings, now)
                store.close()
            write_status(settings, status)
        return code


def _fill_counts(status: dict[str, Any], store: Store, settings: Settings, now: int) -> None:
    live, deleted = store.counts()
    since = pending_since(store)
    last_build = store.get_meta(LAST_BUILD_AT)
    status.update(
        {
            "posts_total": live,
            "posts_deleted": deleted,
            "pending": since is not None,
            "pending_since": _iso(since, settings),
            "builds_today": builds_today(store, now, settings.tz),
            "max_builds_per_day": settings.max_builds_per_day,
            "last_build_at": _iso(int(last_build), settings) if last_build else None,
        }
    )


def _log_result(r: SyncResult) -> None:
    log.info(
        "посты: %s; удалено: %s; по сроку: %s; полная сверка: %s; фото: %s; news.json %s; сборка: %s",
        {c.value: n for c, n in r.changes.items()} or "нет",
        r.deleted,
        r.expired,
        "да" if r.full_reconcile else "нет",
        r.photos,
        "изменился" if r.news_changed else "без изменений",
        "нужна" if r.build_now else ("отложена (лимит)" if r.pending else "не нужна"),
    )
