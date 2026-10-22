"""Один проход синка: окно VK -> (раз в сутки) полная сверка -> фото -> news.json -> решение о сборке.

Сама сборка и переключение релиза - P1-6, блокировка, статус и коды выхода - P1-5.
"""

from collections import Counter
from dataclasses import dataclass, field

import httpx

from pipeline.builds import build_allowed, mark_pending, pending_since
from pipeline.export import build_news, write_news
from pipeline.reconcile import full_reconcile, full_reconcile_due, mark_full_reconciled, reconcile_window
from pipeline.settings import Settings
from pipeline.store.state import Change, Store
from pipeline.sync import download_photos
from pipeline.vk.client import VkClient


@dataclass
class SyncResult:
    changes: Counter[Change] = field(default_factory=Counter)
    deleted: int = 0
    full_reconcile: bool = False
    photos: int = 0
    news_changed: bool = False
    pending: bool = False  # сайт устарел (с этого или прошлых запусков)
    build_now: bool = False  # собирать в этом запуске: есть что и лимит не исчерпан


def run_sync(store: Store, vk: VkClient, http: httpx.Client, settings: Settings, now: int) -> SyncResult:
    """Повод к сборке один: изменился news.json. Счетчики лайков его не меняют, правки, удаления,
    закреп и докачанные фото - меняют. Несколько изменений за запуск - одна сборка."""
    tz = settings.tz
    result = SyncResult()
    window = reconcile_window(store, vk, settings.vk_window, settings.vk_page_size, now)
    result.changes += window.changes
    if full_reconcile_due(store, now, tz, settings.reconcile_after_hour):
        full = full_reconcile(store, vk, settings.vk_by_id_batch, now)  # SyncError/VkError - наружу
        result.changes += full.changes
        result.deleted = full.deleted
        result.full_reconcile = True
        mark_full_reconciled(store, now, tz)
    result.photos = download_photos(store, http, settings.site.media, now)
    result.news_changed = write_news(settings.data.news_json, build_news(store, settings.site.media, now))
    if result.news_changed:
        mark_pending(store, now)
    result.pending = pending_since(store) is not None
    result.build_now = build_allowed(store, now, tz, settings.max_builds_per_day)
    return result
