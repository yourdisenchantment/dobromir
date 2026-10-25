"""Срок хранения новостей (NEWS_RETENTION_DAYS): старше - удаляются целиком, назад не попадают."""

import io
import json
from pathlib import Path

import pytest

from fakevk import FakeWall
from pipeline.settings import Settings, load_settings
from pipeline.store import Store, open_db
from pipeline.sync import ingest
from pipeline.worker import EXIT_OK, run_worker
from samples import GROUP, post_obj

DAY = 86400
WALL = 1786000000  # дата постов FakeWall: 6 августа 2026 (плюс минута на пост)


def settings_at(tmp_path: Path, **extra: str) -> Settings:
    env = {
        "DOBROMIR_DATA": str(tmp_path / "data"),
        "SITE_ROOT": str(tmp_path / "site"),
        "SITE_ENV": "staging",
        "VK_SERVICE_TOKEN": "vk1.a.RETENTION-SECRET",
        "VK_GROUP_ID": str(GROUP),
        **extra,
    }
    return load_settings(env)


def test_default_is_30_days_and_bounds(tmp_path: Path) -> None:
    assert settings_at(tmp_path).news_retention_days == 30
    assert settings_at(tmp_path, NEWS_RETENTION_DAYS="90").news_retention_days == 90
    with pytest.raises(RuntimeError, match="NEWS_RETENTION_DAYS"):
        settings_at(tmp_path, NEWS_RETENTION_DAYS="0")


def test_ingest_skips_posts_older_than_since(tmp_path: Path) -> None:
    store = Store(open_db(tmp_path / "db.sqlite"))
    response = {"items": [post_obj(1, date=WALL), post_obj(2, date=WALL - 40 * DAY)]}
    ingest(store, [response], WALL, since=WALL - 30 * DAY)
    assert [sp.post.id for sp in store.posts(include_deleted=True)] == [1]
    store.close()


def test_expire_posts_deletes_old_rows_only(tmp_path: Path) -> None:
    store = Store(open_db(tmp_path / "db.sqlite"))
    for post_id, age in ((1, 1), (2, 29), (3, 31), (4, 400)):
        store.upsert(post_obj(post_id, date=WALL - age * DAY), WALL)
    store.mark_deleted([(-GROUP, 2), (-GROUP, 3)], WALL)  # удаленные в VK тоже уходят по сроку
    assert store.expire_posts(WALL - 30 * DAY) == 2
    assert sorted(sp.post.id for sp in store.posts(include_deleted=True)) == [1, 2]
    store.close()


def news(s: Settings) -> list[int]:
    return [p["id"] for p in json.loads(s.data.news_json.read_text(encoding="utf-8"))["posts"]]


def test_worker_drops_expired_news_and_does_not_take_them_back(tmp_path: Path) -> None:
    """Через срок хранения новость уходит с сайта, хотя в группе VK она есть и попадает в окно."""
    s = settings_at(tmp_path, VK_WINDOW="20")
    wall = FakeWall(3)
    builds: list[int] = []

    def run(now: int) -> int:
        return run_worker(s, wall.http(), now=now, build=lambda st, n: builds.append(n), stderr=io.StringIO())

    assert run(WALL + 10 * DAY) == EXIT_OK
    assert news(s) == [3, 2, 1] and len(builds) == 1

    assert run(WALL + 31 * DAY) == EXIT_OK  # все три старше 30 дней
    assert news(s) == [] and len(builds) == 2  # уход новостей - тоже повод собрать сайт
    store = Store(open_db(s.data.db))
    assert store.posts(include_deleted=True) == []  # в базе их тоже нет
    store.close()

    assert run(WALL + 31 * DAY + 3600) == EXIT_OK  # окно снова их видит - назад не берем
    assert news(s) == [] and len(builds) == 2  # и лишней сборки нет
