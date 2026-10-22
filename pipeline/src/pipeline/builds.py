"""Когда собирать сайт: флаг «сайт устарел» и суточный лимит сборок.

Флаг хранится в базе, а не держится до следующего запуска в памяти: если сборка
не случилась (лимит, сбой), изменения не теряются и соберутся позже. Сутки - по
местному времени (TZ_NAME), а не по UTC.
"""

from zoneinfo import ZoneInfo

from pipeline.reconcile import local_date
from pipeline.store.state import Store

PENDING_SINCE = "pending_since"
BUILDS_DATE = "builds_date"
BUILDS_TODAY = "builds_today"
LAST_BUILD_AT = "last_build_at"


def mark_pending(store: Store, now: int) -> None:
    """Сайт устарел. Время первого неотработанного изменения сохраняется (не перезаписывается)."""
    if store.get_meta(PENDING_SINCE) is None:
        store.set_meta(PENDING_SINCE, str(now))


def pending_since(store: Store) -> int | None:
    value = store.get_meta(PENDING_SINCE)
    return None if value is None else int(value)


def builds_today(store: Store, now: int, tz: ZoneInfo) -> int:
    """Сколько сборок было за текущие местные сутки; в новых сутках счет с нуля."""
    if store.get_meta(BUILDS_DATE) != local_date(now, tz):
        return 0
    return int(store.get_meta(BUILDS_TODAY) or 0)


def build_allowed(store: Store, now: int, tz: ZoneInfo, max_per_day: int) -> bool:
    """Собирать сейчас: есть неотработанные изменения и лимит на сегодня не исчерпан."""
    return pending_since(store) is not None and builds_today(store, now, tz) < max_per_day


def record_build(store: Store, now: int, tz: ZoneInfo) -> None:
    """Успешная сборка: счетчик +1, флаг снят. Неудачную сборку не записывать - флаг должен остаться."""
    today = local_date(now, tz)
    count = builds_today(store, now, tz) + 1
    store.set_meta(BUILDS_DATE, today)
    store.set_meta(BUILDS_TODAY, str(count))
    store.set_meta(LAST_BUILD_AT, str(now))
    store.delete_meta(PENDING_SINCE)
