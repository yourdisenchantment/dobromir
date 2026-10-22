"""Стадия 1. Единственная, что ходит в сеть: забирает ответы VK и кладет их как есть, ничего не разбирая."""

from pipeline.fetch.rawlog import RawLog

__all__ = ["RawLog"]
