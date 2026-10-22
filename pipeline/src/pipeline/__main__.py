"""Запуск: `uv run python -m pipeline process`."""

import argparse
import logging

import httpx

from pipeline.settings import load_settings
from pipeline.sync import process


def main() -> None:
    parser = argparse.ArgumentParser(prog="pipeline")
    parser.add_argument(
        "command",
        choices=["process"],
        help="process - пересобрать контент из сырого",
    )
    parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx пишет адреса запросов, а в них ключи

    settings = load_settings()
    with httpx.Client() as http:
        logging.info("постов в контенте: %s", process(settings.data, settings.site.media, http))


if __name__ == "__main__":
    main()
