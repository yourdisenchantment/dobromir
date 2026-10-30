"""Один проход синка: (на свежей базе) первичная загрузка -> окно VK -> (раз в сутки) полная сверка ->
фото -> news.json -> решение о сборке.

Сама сборка и переключение релиза - P1-6, блокировка, статус и коды выхода - P1-5.
"""

from collections import Counter
from dataclasses import dataclass, field

import httpx

from pipeline.builds import build_allowed, mark_pending, pending_since
from pipeline.export import build_news, write_news
from pipeline.reconcile import (
    fetch_wall,
    full_reconcile,
    full_reconcile_due,
    mark_full_reconciled,
    reconcile_window,
)
from pipeline.settings import Settings
from pipeline.store.state import Change, Store
from pipeline.sync import download_photos, ingest
from pipeline.vk.client import VkClient

BACKFILL_DONE = "backfill_done_at"


@dataclass
class SyncResult:
    changes: Counter[Change] = field(default_factory=Counter)
    deleted: int = 0
    expired: int = 0  # удалено по сроку хранения
    backfill: bool = False  # в этом запуске была первичная загрузка
    full_reconcile: bool = False
    photos: int = 0
    news_changed: bool = False
    pending: bool = False  # сайт устарел (с этого или прошлых запусков)
    build_now: bool = False  # собирать в этом запуске: есть что и лимит не исчерпан


def retention_start(settings: Settings, now: int) -> int:
    """Самая ранняя дата публикации, которая еще хранится и показывается."""
    return now - settings.news_retention_days * 86400


def backfill(store: Store, vk: VkClient, settings: Settings, now: int) -> Counter[Change]:
    """Первичная загрузка: все посты стены за срок хранения. Отмечается в базе, повторно не нужна."""
    since = retention_start(settings, now)
    changes = ingest(store, [fetch_wall(vk, None, settings.vk_page_size, since)], now, since)
    store.set_meta(BACKFILL_DONE, str(now))
    return changes


def run_sync(
    store: Store, vk: VkClient, http: httpx.Client, settings: Settings, now: int, *, force_full: bool = False
) -> SyncResult:
    """Повод к сборке один: изменился news.json. Счетчики лайков его не меняют, правки, удаления,
    закреп и докачанные фото - меняют. Несколько изменений за запуск - одна сборка.

    force_full - полная сверка сейчас, не дожидаясь суточной (ручная проверка, `sync --full`)."""
    tz = settings.tz
    result = SyncResult()
    since = retention_start(settings, now)
    result.expired = store.expire_posts(since)  # сначала срок: сверять старое незачем
    if store.get_meta(BACKFILL_DONE) is None:
        # Свежая база: окно (VK_WINDOW) короче срока хранения, без этого посты срока старше
        # окна на сайт не попали бы никогда (найдено при обзоре 2026-10-27).
        result.changes += backfill(store, vk, settings, now)
        result.backfill = True
    window = reconcile_window(store, vk, settings.vk_window, settings.vk_page_size, now, since)
    result.changes += window.changes
    result.deleted = window.deleted
    if force_full or full_reconcile_due(store, now, tz, settings.reconcile_after_hour):
        full = full_reconcile(store, vk, settings.vk_by_id_batch, now, since)  # SyncError/VkError - наружу
        result.changes += full.changes
        result.deleted += full.deleted
        result.full_reconcile = True
        mark_full_reconciled(store, now, tz)
    result.photos = download_photos(store, http, settings.site.media, now)
    result.news_changed = write_news(settings.data.news_json, build_news(store, settings.site.media, now))
    if result.news_changed:
        mark_pending(store, now)
    result.pending = pending_since(store) is not None
    result.build_now = build_allowed(store, now, tz, settings.max_builds_per_day)
    return result
