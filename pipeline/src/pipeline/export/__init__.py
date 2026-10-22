"""Стадия 3. Превращает разобранные записи в то, что читает сайт."""

from pipeline.export.news import build_news, write_news

__all__ = ["build_news", "write_news"]
