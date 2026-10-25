"""Сверка и решение о сборке - обязательные случаи из отчета о хостинге, разд. 9 п. 16."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from fakevk import FakeWall
from pipeline.builds import build_allowed, builds_today, mark_pending, pending_since, record_build
from pipeline.reconcile import (
    SyncError,
    classify_missing,
    fetch_wall,
    full_reconcile,
    full_reconcile_due,
    mark_full_reconciled,
)
from pipeline.run import run_sync
from pipeline.settings import Settings, load_settings
from pipeline.store import Store, open_db
from pipeline.sync import ingest
from pipeline.vk.client import VkApiError

TZ = ZoneInfo("Europe/Simferopol")


def at(day: int, hour: int, minute: int = 0) -> int:
    """Момент по Симферополю, октябрь 2026."""
    return int(datetime(2026, 10, day, hour, minute, tzinfo=TZ).timestamp())


def settings_at(tmp_path: Path, **extra: str) -> Settings:
    env = {
        "DOBROMIR_DATA": str(tmp_path / "data"),
        "SITE_ROOT": str(tmp_path / "site"),
        "SITE_ENV": "staging",
        "VK_WINDOW": "5",
        # Посты FakeWall - августовские, «сейчас» - октябрь: срок хранения здесь не проверяется.
        "NEWS_RETENTION_DAYS": "3650",
        "VK_PAGE_SIZE": "10",
        "VK_BY_ID_BATCH": "4",
        **extra,
    }
    return load_settings(env)


def no_photos() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    s = Store(open_db(tmp_path / "db.sqlite"))
    yield s
    s.close()


def live_ids(store: Store) -> list[int]:
    return sorted(i for _, i in store.live_keys())


def backfill(store: Store, wall: FakeWall, now: int) -> None:
    """Первичная загрузка всей стены - так база заполняется в жизни, до работы по окну."""
    ingest(store, [fetch_wall(wall.client(), limit=None, page_size=10)], now)


def sync(store: Store, wall: FakeWall, settings: Settings, now: int):  # type: ignore[no-untyped-def]
    with no_photos() as http:
        return run_sync(store, wall.client(), http, settings, now)


# --- окно ---


def test_window_takes_newest_and_pinned_once() -> None:
    wall = FakeWall(20)
    wall.pin(2)  # старый пост закреплен
    resp = fetch_wall(wall.client(), limit=5, page_size=10)
    ids = [p["id"] for p in resp["items"]]
    assert ids == [2, 20, 19, 18, 17, 16]  # закреп + 5 новых, закреп не дублируется


def test_backfill_whole_wall_with_paging() -> None:
    wall = FakeWall(57)
    resp = fetch_wall(wall.client(), limit=None, page_size=10)
    assert sorted(p["id"] for p in resp["items"]) == list(range(1, 58))
    assert wall.calls.count("wall.get") >= 6


def test_pinned_outside_window_is_not_deleted(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(10)
    s = settings_at(tmp_path, VK_WINDOW="3")
    store.upsert(wall.posts[1], at(23, 1))
    wall.pin(1)
    sync(store, wall, s, at(23, 2))  # до 03:00 - только окно
    assert 1 in live_ids(store)
    sync(store, wall, s, at(23, 4))  # полная сверка
    assert 1 in live_ids(store)


# --- решение о сборке ---


def test_text_edit_needs_build_counters_do_not(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(6)
    s = settings_at(tmp_path)
    first = sync(store, wall, s, at(23, 1))
    assert first.news_changed and first.build_now
    record_build(store, at(23, 1), TZ)

    wall.edit(6, likes={"count": 99}, views={"count": 500}, comments={"count": 3}, reposts={"count": 2})
    counters = sync(store, wall, s, at(23, 2))
    assert not counters.news_changed and not counters.pending and not counters.build_now

    wall.edit(6, text="Исправленный текст", edited=at(23, 2))
    edit = sync(store, wall, s, at(23, 2, 30))
    assert edit.news_changed and edit.build_now


def test_new_post_needs_build(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(3)
    s = settings_at(tmp_path)
    sync(store, wall, s, at(23, 1))
    record_build(store, at(23, 1), TZ)
    wall.add(4)
    r = sync(store, wall, s, at(23, 2))
    assert r.changes["new"] == 1 and r.build_now


# --- удаление и восстановление ---


def test_recent_deletion_found_by_window_within_the_hour(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(10)
    s = settings_at(tmp_path)  # окно 5: посты 6-10
    backfill(store, wall, at(23, 1))
    sync(store, wall, s, at(23, 1))
    wall.delete(9)
    r = sync(store, wall, s, at(23, 2))  # до 03:00 - сверки нет, удаление замечает окно
    assert not r.full_reconcile and r.deleted == 1 and 9 not in live_ids(store) and r.build_now


def test_old_deletion_found_by_daily_reconcile(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(10)
    s = settings_at(tmp_path)  # окно 5: посты 6-10, пост 2 - старше окна
    backfill(store, wall, at(23, 1))
    sync(store, wall, s, at(23, 1))
    wall.delete(2)
    r = sync(store, wall, s, at(23, 2))  # окно старый пост не судит
    assert 2 in live_ids(store) and r.deleted == 0
    r = sync(store, wall, s, at(23, 4))  # после 03:00 - полная сверка
    assert r.full_reconcile and r.deleted == 1 and 2 not in live_ids(store) and r.build_now


def test_old_pinned_post_does_not_stretch_window(store: Store, tmp_path: Path) -> None:
    """Закреп VK отдает первым; если бы его дата задавала границу окна, все посты между ним
    и окном считались бы удаленными."""
    wall = FakeWall(10)
    s = settings_at(tmp_path)
    backfill(store, wall, at(23, 1))
    wall.pin(1)
    r = sync(store, wall, s, at(23, 2))
    assert r.deleted == 0 and live_ids(store) == list(range(1, 11))


def test_incomplete_or_empty_window_deletes_nothing(store: Store, tmp_path: Path) -> None:
    from pipeline.reconcile import window_missing

    wall = FakeWall(10)
    backfill(store, wall, at(23, 1))
    full = fetch_wall(wall.client(), limit=5, page_size=10)
    assert full["complete"] is True
    partial = {**full, "items": full["items"][:2], "complete": False}
    assert window_missing(store, partial) == set()
    assert window_missing(store, {"items": [], "complete": True}) == set()


def test_mass_deletion_in_window_refused(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(10)
    s = settings_at(tmp_path, VK_WINDOW="8")
    backfill(store, wall, at(23, 1))
    for i in (10, 9, 8, 7):  # 4 свежих из 10 - больше порога
        wall.delete(i)
    with pytest.raises(SyncError, match="окно"):
        sync(store, wall, s, at(23, 2))
    assert live_ids(store) == list(range(1, 11))


def test_restored_post_comes_back(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(10)
    s = settings_at(tmp_path)
    backfill(store, wall, at(23, 1))
    sync(store, wall, s, at(23, 1))
    hidden = wall.posts[10]
    wall.delete(10)  # например, пост скрыли в VK
    gone = sync(store, wall, s, at(23, 2))  # свежий - его снимает окно
    assert gone.deleted == 1 and 10 not in live_ids(store) and gone.news_changed
    wall.posts[10] = hidden  # и вернули
    back = sync(store, wall, s, at(23, 5))
    assert back.changes["restored"] == 1 and 10 in live_ids(store) and back.news_changed


def test_mass_deletion_refused_and_db_unchanged(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(10)
    s = settings_at(tmp_path)
    backfill(store, wall, at(23, 1))
    sync(store, wall, s, at(23, 1))
    for i in (1, 2, 3, 4):  # 4 из 10 - больше порога max(3, 20%)
        wall.delete(i)
    with pytest.raises(SyncError, match="4 из 10"):
        full_reconcile(store, wall.client(), batch=4, now=at(23, 4))
    assert live_ids(store) == list(range(1, 11))


def test_three_deletions_are_allowed(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(10)
    s = settings_at(tmp_path)
    backfill(store, wall, at(23, 1))
    sync(store, wall, s, at(23, 1))
    for i in (1, 2, 3):
        wall.delete(i)
    r = full_reconcile(store, wall.client(), batch=4, now=at(23, 4))
    assert r.deleted == 3 and live_ids(store) == list(range(4, 11))


def test_vk_error_during_reconcile_deletes_nothing(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(10)
    s = settings_at(tmp_path)
    backfill(store, wall, at(23, 1))
    sync(store, wall, s, at(23, 1))
    wall.delete(5)
    wall.fail_methods.add("wall.getById")
    with pytest.raises(VkApiError):
        sync(store, wall, s, at(23, 4))
    assert 5 in live_ids(store)
    assert full_reconcile_due(store, at(23, 5), TZ, 3)  # сверка не отмечена - повторится


def test_empty_answer_is_not_deletion(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(10)
    s = settings_at(tmp_path)
    backfill(store, wall, at(23, 1))
    sync(store, wall, s, at(23, 1))
    wall.empty_by_id = True
    r = sync(store, wall, s, at(23, 4))
    assert r.full_reconcile and r.deleted == 0 and live_ids(store) == list(range(1, 11))


def test_classify_missing() -> None:
    empty: dict[str, list[dict[str, int]]] = {"items": []}
    assert classify_missing([([1, 2, 3], empty)]) == set()  # все пусто - не знаем
    assert classify_missing([([1, 2], empty), ([3, 4], empty)]) == set()
    assert classify_missing([([1, 2, 3], {"items": [{"id": 1}, {"id": 3}]})]) == {2}
    assert classify_missing([([1, 2], {"items": [{"id": 1}, {"id": 2, "is_deleted": True}]})]) == {2}
    # пустая пачка при ответивших остальных - ее посты удалены
    assert classify_missing([([5, 6], {"items": [{"id": 5}, {"id": 6}]}), ([1, 2], empty)]) == {1, 2}


def test_oldest_posts_alone_in_last_batch_are_deleted(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(9)  # пачки по 4: [9-6], [5-2], [1]
    backfill(store, wall, at(23, 1))
    wall.delete(1)
    r = full_reconcile(store, wall.client(), batch=4, now=at(23, 4))
    assert r.deleted == 1 and 1 not in live_ids(store)


# --- сутки и лимит ---


def test_full_reconcile_once_a_day_after_3(store: Store) -> None:
    assert not full_reconcile_due(store, at(23, 2, 59), TZ, 3)
    assert full_reconcile_due(store, at(23, 3, 0), TZ, 3)
    mark_full_reconciled(store, at(23, 3, 0), TZ)
    assert not full_reconcile_due(store, at(23, 23, 59), TZ, 3)
    assert not full_reconcile_due(store, at(24, 0, 1), TZ, 3)  # новые сутки, но до 03:00
    assert full_reconcile_due(store, at(24, 3, 17), TZ, 3)


def test_build_limit_keeps_pending_until_next_day(store: Store) -> None:
    for minute in range(4):  # 4 сборки в день - лимит
        mark_pending(store, at(23, 10, minute))
        assert build_allowed(store, at(23, 10, minute), TZ, 4)
        record_build(store, at(23, 10, minute), TZ)
    mark_pending(store, at(23, 20))
    assert not build_allowed(store, at(23, 23, 59), TZ, 4)  # лимит исчерпан
    assert pending_since(store) == at(23, 20)  # изменение не потеряно
    assert build_allowed(store, at(24, 0, 1), TZ, 4)  # новые сутки по Симферополю
    assert builds_today(store, at(24, 0, 1), TZ) == 0


def test_day_boundary_is_local_not_utc(store: Store) -> None:
    """23:30 по Симферополю - это 20:30 UTC: сутки те же. 00:30 - уже новые, хотя в UTC еще вчера."""
    record_build(store, at(23, 23, 30), TZ)
    assert builds_today(store, at(23, 23, 59), TZ) == 1
    assert builds_today(store, at(24, 0, 30), TZ) == 0


def test_pending_survives_failed_build(store: Store) -> None:
    mark_pending(store, at(23, 10))
    mark_pending(store, at(23, 11))  # время первого изменения не перезаписывается
    assert pending_since(store) == at(23, 10)
    # сборка упала - record_build не вызван - флаг на месте
    assert build_allowed(store, at(23, 12), TZ, 4)


def test_build_not_needed_without_changes(store: Store, tmp_path: Path) -> None:
    wall = FakeWall(3)
    s = settings_at(tmp_path)
    sync(store, wall, s, at(23, 1))
    record_build(store, at(23, 1), TZ)
    r = sync(store, wall, s, at(23, 2))
    assert not r.news_changed and not r.build_now and r.changes["same"] == 3
