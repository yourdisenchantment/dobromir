from pathlib import Path

from pipeline.store import Change, Store, open_db
from samples import GROUP, post_obj

NOW = 1786100000


def store_at(tmp_path: Path) -> Store:
    return Store(open_db(tmp_path / "db.sqlite"))


def test_new_same_changed(tmp_path: Path) -> None:
    s = store_at(tmp_path)
    assert s.upsert(post_obj(1), NOW) == Change.NEW
    assert s.upsert(post_obj(1), NOW + 1) == Change.SAME
    assert s.upsert(post_obj(1, likes={"count": 50}, views={"count": 9}), NOW + 2) == Change.SAME
    assert s.upsert(post_obj(1, text="Правка"), NOW + 3) == Change.CHANGED
    assert s.upsert(post_obj(1, text="Правка", edited=NOW + 3), NOW + 4) == Change.CHANGED
    s.close()


def test_pin_change_is_a_change(tmp_path: Path) -> None:
    s = store_at(tmp_path)
    s.upsert(post_obj(1), NOW)
    assert s.upsert(post_obj(1, is_pinned=1), NOW) == Change.CHANGED
    assert s.upsert(post_obj(1, is_pinned=1), NOW) == Change.SAME
    assert s.upsert(post_obj(1), NOW) == Change.CHANGED  # открепили
    s.close()


def test_raw_json_always_latest(tmp_path: Path) -> None:
    s = store_at(tmp_path)
    s.upsert(post_obj(1, likes={"count": 1}), NOW)
    s.upsert(post_obj(1, likes={"count": 7}), NOW)
    [stored] = s.posts()
    assert stored.raw["likes"] == {"count": 7}
    s.close()


def test_soft_delete_and_restore(tmp_path: Path) -> None:
    s = store_at(tmp_path)
    s.upsert(post_obj(1), NOW)
    s.upsert(post_obj(2), NOW)
    assert s.mark_deleted([(-GROUP, 1)], NOW) == 1
    assert s.mark_deleted([(-GROUP, 1)], NOW) == 0  # уже удален
    assert [p.post.id for p in s.posts()] == [2]
    assert {p.post.id for p in s.posts(include_deleted=True)} == {1, 2}
    assert s.live_keys() == [(-GROUP, 2)]
    assert s.upsert(post_obj(1), NOW + 5) == Change.RESTORED
    assert {p.post.id for p in s.posts()} == {1, 2}
    s.close()


def test_meta(tmp_path: Path) -> None:
    s = store_at(tmp_path)
    assert s.get_meta("builds_today") is None
    s.set_meta("builds_today", "1")
    s.set_meta("builds_today", "2")
    assert s.get_meta("builds_today") == "2"
    s.close()


def test_data_survives_reopen(tmp_path: Path) -> None:
    s = store_at(tmp_path)
    s.upsert(post_obj(1), NOW)
    s.set_meta("k", "v")
    s.close()
    s = store_at(tmp_path)
    assert [p.post.id for p in s.posts()] == [1] and s.get_meta("k") == "v"
    s.close()
