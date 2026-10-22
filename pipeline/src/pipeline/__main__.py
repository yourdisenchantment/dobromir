"""Запуск: `uv run python -m pipeline <команда>`; список команд - `--help`."""

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Literal, cast

import httpx

from pipeline.export import build_news, write_news
from pipeline.reconcile import fetch_wall
from pipeline.run import run_sync
from pipeline.settings import load_settings
from pipeline.store import Store, open_db
from pipeline.survey import run_survey
from pipeline.sync import download_photos, ingest
from pipeline.vk.client import VkClient


def main() -> None:
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    survey = sub.add_parser(
        "survey",
        help="разведка стены: какие поля отдает VK и сколько постов видит ключ (только чтение)",
    )
    survey.add_argument("--key", choices=["community", "service", "both"], default="both")
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
    sub.add_parser("backfill", help="загрузить в базу всю стену VK (первичная загрузка)")
    sub.add_parser("sync", help="один проход: окно VK, суточная сверка, фото, news.json; без сборки")
    args = parser.parse_args()
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
                    changes = ingest(store, [fetch_wall(vk, None, settings.vk_page_size)], now)
                    logging.info("записано: %s", {c.value: n for c, n in changes.items()} or "ничего")
                else:
                    r = run_sync(store, vk, http, settings, now)
                    logging.info(
                        "посты: %s; удалено: %s; полная сверка: %s; фото: %s; news.json %s; сборка: %s",
                        {c.value: n for c, n in r.changes.items()} or "нет",
                        r.deleted,
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


if __name__ == "__main__":
    main()
