"""Запуск: `uv run python -m pipeline <команда>`; список команд - `--help`."""

import argparse
import json
import logging
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Literal, cast

import httpx

from pipeline.backup import BackupError, backup_db
from pipeline.export import build_news, write_news
from pipeline.media.cleanup import cleanup_media
from pipeline.release import ReleaseError, build_release, rollback
from pipeline.run import backfill, run_sync
from pipeline.settings import Settings, load_settings
from pipeline.store import Store, open_db
from pipeline.store.db import migrate, schema_version
from pipeline.survey import run_survey
from pipeline.sync import download_photos, ingest
from pipeline.vk.client import VkClient
from pipeline.worker import EXIT_ERROR, run_worker, single_instance


def main() -> None:
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    survey = sub.add_parser(
        "survey",
        help="разведка стены: какие поля отдает VK и сколько постов видит ключ (только чтение)",
    )
    survey.add_argument("--key", choices=["community", "service", "both"], default="service")
    survey.add_argument(
        "--token-in",
        choices=["header", "body"],
        default="header",
        help="как передавать ключ: заголовок Authorization или параметр access_token",
    )
    survey.add_argument("--max-pages", type=int, default=50, help="предохранитель от бесконечного листания")
    load = sub.add_parser("import", help="загрузить в базу сохраненные ответы wall.get (без сети)")
    load.add_argument("files", nargs="+", type=Path, help="JSON-файлы ответов, например из survey")
    sub.add_parser("photos", help="скачать фото живых постов, которых еще нет")
    sub.add_parser("export", help="записать news.json из базы")
    sub.add_parser("backfill", help="первичная загрузка: посты стены VK за срок хранения (NEWS_RETENTION_DAYS)")
    sync = sub.add_parser("sync", help="один проход: окно VK, суточная сверка, фото, news.json; без сборки")
    sync.add_argument("--full", action="store_true", help="полная сверка через wall.getById сейчас, не раз в сутки")
    sub.add_parser("worker", help="запуск из cron: блокировка, синк, сборка, status.json, коды выхода")
    back = sub.add_parser("rollback", help="вернуть public_html на предыдущий релиз без пересборки")
    back.add_argument("--to", help="имя релиза из releases/ (любого, не только старого); по умолчанию - предыдущий")
    build = sub.add_parser("build", help="собрать и проверить релиз в releases/; public_html не трогать")
    build.add_argument("--switch", action="store_true", help="после проверок переключить public_html на него")
    sub.add_parser("migrate", help="довести схему базы до последней версии (deploy.sh)")
    sub.add_parser("backup", help="копия базы в <данные>/backup/, хранить 7 последних")
    clean = sub.add_parser("media-cleanup", help="удалить фото, на которые не ссылается ни один пост в базе")
    clean.add_argument("--dry-run", action="store_true", help="только показать, что удалилось бы")
    args = parser.parse_args()
    if args.command == "worker":
        sys.exit(worker_main())
    if args.command == "rollback":
        sys.exit(rollback_main(args.to))
    if args.command == "build":
        sys.exit(build_main(switch=args.switch))
    if args.command == "migrate":
        sys.exit(migrate_main())
    if args.command == "backup":
        sys.exit(backup_main())
    if args.command == "media-cleanup":
        sys.exit(media_cleanup_main(dry_run=args.dry_run))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx пишет адреса запросов

    settings = load_settings()
    now = int(time.time())
    if args.command == "survey":
        with httpx.Client() as http:
            keys = ["community", "service"] if args.key == "both" else [args.key]
            token_in = cast(Literal["header", "body"], args.token_in)
            clients = {k: VkClient(settings.vk(k), http, token_in=token_in) for k in keys}
            report = run_survey(clients, settings.data.root / "survey", settings.vk_page_size, args.max_pages)
        print(report.read_text(encoding="utf-8"))
        print(f"\nОтчет: {report}")
        return

    store = Store(open_db(settings.data.db))
    try:
        if args.command == "import":
            responses = [json.loads(f.read_text(encoding="utf-8")) for f in args.files]
            changes = ingest(store, responses, now)
            logging.info("записано: %s", {c.value: n for c, n in changes.items()} or "ничего")
        elif args.command in ("backfill", "sync"):
            with httpx.Client() as http:
                vk = VkClient(settings.vk(), http)
                if args.command == "backfill":
                    changes = backfill(store, vk, settings, now)
                    logging.info("записано: %s", {c.value: n for c, n in changes.items()} or "ничего")
                else:
                    r = run_sync(store, vk, http, settings, now, force_full=args.full)
                    logging.info(
                        "посты: %s; удалено: %s; по сроку: %s; полная сверка: %s; фото: %s; news.json %s; сборка: %s",
                        {c.value: n for c, n in r.changes.items()} or "нет",
                        r.deleted,
                        r.expired,
                        "да" if r.full_reconcile else "нет",
                        r.photos,
                        "изменился" if r.news_changed else "без изменений",
                        "нужна" if r.build_now else ("отложена (лимит)" if r.pending else "не нужна"),
                    )
        elif args.command == "photos":
            with httpx.Client() as http:
                logging.info("скачано фото: %s", download_photos(store, http, settings.site.media, now))
        else:
            news = build_news(store, settings.site.media, now)
            changed = write_news(settings.data.news_json, news)
            logging.info(
                "постов в news.json: %s (%s): %s",
                len(news["posts"]),
                "изменился" if changed else "без изменений",
                settings.data.news_json,
            )
    finally:
        store.close()


def _settings_or_none() -> Settings | None:
    """Настройки для команд из shell-скриптов: при ошибке одна строка вместо трейсбека."""
    try:
        return load_settings()
    except RuntimeError as exc:
        print(f"Неверные настройки: {exc}", file=sys.stderr)
        return None


def media_cleanup_main(*, dry_run: bool) -> int:
    """Под блокировкой воркера: он сам чистит медиа раз в сутки и пишет в ту же базу."""
    settings = _settings_or_none()
    if settings is None:
        return EXIT_ERROR
    with single_instance(settings) as acquired:
        if not acquired:
            print("Воркер сейчас работает, повторите через несколько минут.", file=sys.stderr)
            return EXIT_ERROR
        store = Store(open_db(settings.data.db))
        try:
            result = cleanup_media(store, settings.site.media, dry_run=dry_run)
        finally:
            store.close()
    for name in result.removed:
        print(name)
    verb = "файлов удалилось бы" if dry_run else "файлов удалено"
    print(f"{verb}: {len(result.removed)}; не тронуто: {len(result.refused)}")
    return 0


def worker_main() -> int:
    """Без логов на экран: из cron любой вывод уходит письмом, поэтому печатается только ошибка."""
    try:
        settings = load_settings()
    except RuntimeError as exc:
        print(f"Воркер не запущен: неверные настройки. {exc}", file=sys.stderr)
        return EXIT_ERROR
    with httpx.Client() as http:
        return run_worker(settings, http, build=build_release)


def rollback_main(to: str | None) -> int:
    """Откат под той же блокировкой, что и воркер: не переключать ссылку посреди его сборки."""
    settings = _settings_or_none()
    if settings is None:
        return EXIT_ERROR
    with single_instance(settings) as acquired:
        if not acquired:
            print("Воркер сейчас работает, повторите откат через несколько минут.", file=sys.stderr)
            return EXIT_ERROR
        try:
            target = rollback(settings.site, to)
        except ReleaseError as exc:
            print(f"Откат не выполнен: {exc}", file=sys.stderr)
            return EXIT_ERROR
    print(f"public_html теперь указывает на {target.name}")
    return 0


def build_main(*, switch: bool) -> int:
    """Сборка вне cron (deploy.sh): под блокировкой воркера, ход сборки - в консоль."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = _settings_or_none()
    if settings is None:
        return EXIT_ERROR
    with single_instance(settings) as acquired:
        if not acquired:
            print("Воркер сейчас работает, повторите сборку через несколько минут.", file=sys.stderr)
            return EXIT_ERROR
        try:
            release = build_release(settings, int(time.time()), switch=switch)
        except ReleaseError as exc:
            print(f"Релиз не собран, сайт не тронут: {exc}", file=sys.stderr)
            return EXIT_ERROR
    if switch:
        print(f"public_html теперь указывает на {release.name}")
    else:
        print(f"Релиз {release.name} собран и проверен, public_html не тронут.")
        # Полный путь: на сервере системный python пакета не видит, нужен Python из venv.
        print(f"Включить: {sys.executable} -m pipeline rollback --to {release.name}")
    return 0


def migrate_main() -> int:
    """Миграции под блокировкой воркера: не менять схему посреди его записи."""
    settings = _settings_or_none()
    if settings is None:
        return EXIT_ERROR
    with single_instance(settings) as acquired:
        if not acquired:
            print("Воркер сейчас работает, повторите через несколько минут.", file=sys.stderr)
            return EXIT_ERROR
        settings.data.db.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(settings.data.db)) as conn:
            before = schema_version(conn)
            after = migrate(conn)
    print(
        f"схема базы: версия {before} -> {after}" if after != before else f"схема базы: версия {after}, без изменений"
    )
    return 0


def backup_main() -> int:
    """Без блокировки: снимок SQLite согласован и при работающем воркере, а копия не должна
    пропадать из-за того, что воркер в это время занят."""
    settings = _settings_or_none()
    if settings is None:
        return EXIT_ERROR
    try:
        path = backup_db(settings, int(time.time()))
    except BackupError as exc:
        print(f"Копия базы не сделана: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"копия базы: {path}")
    return 0


if __name__ == "__main__":
    main()
