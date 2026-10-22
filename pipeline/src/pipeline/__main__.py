"""Запуск: `uv run python -m pipeline <команда>`; список команд - `--help`."""

import argparse
import logging
from typing import Literal, cast

import httpx

from pipeline.settings import load_settings
from pipeline.survey import run_survey
from pipeline.sync import process
from pipeline.vk.client import VkClient


def main() -> None:
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("process", help="пересобрать контент из сырого")
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
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx пишет адреса запросов

    settings = load_settings()
    with httpx.Client() as http:
        if args.command == "process":
            logging.info("постов в контенте: %s", process(settings.data, settings.site.media, http))
            return
        keys = ["community", "service"] if args.key == "both" else [args.key]
        token_in = cast(Literal["header", "body"], args.token_in)
        clients = {k: VkClient(settings.vk(k), http, token_in=token_in) for k in keys}
        report = run_survey(clients, settings.data.root / "survey", settings.vk_page_size, args.max_pages)
        print(report.read_text(encoding="utf-8"))
        print(f"\nОтчет: {report}")


if __name__ == "__main__":
    main()
