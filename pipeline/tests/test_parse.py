import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.fetch.rawlog import RawLog
from pipeline.parse import Post, parse_post, parse_posts, parse_raw, parse_wall
from pipeline.parse.posts import is_news, make_title, source_names
from samples import GROUP, post_obj

FIXTURE = Path(__file__).parent / "fixtures" / "wall_get_antarctic.json"
TEST_GROUP = 242263522


def wall() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def by_id(posts: list[Post]) -> dict[int, Post]:
    return {p.id: p for p in posts}


def test_parse_post_fields() -> None:
    post = parse_post(post_obj())
    assert post.title == "Открытие центра"
    assert post.tags == ["мероприятия", "Добромир"]
    assert [p.id for p in post.photos] == [1, 2]
    assert post.photos[0].url.endswith("1_w.jpg")  # самый большой размер
    assert post.photos[0].uid == f"m{GROUP}_1"
    assert [link.url for link in post.links] == ["https://example.org/a"]
    assert [(m.kind, m.id) for m in post.media] == [("video", 5)]
    assert post.skipped == []
    assert post.pinned is False and post.edited is None and post.repost is None
    assert post.slug == "2026-08-06-vk101"
    assert post.vk_url == f"https://vk.com/wall-{GROUP}_101"


def test_title_truncated_on_word_boundary() -> None:
    title = make_title("слово " * 40)
    assert len(title) <= 121
    assert title.endswith("…")
    assert make_title("\n\n  \n") == ""


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({}, True),
        ({"from_id": 777}, False),  # запись посетителя
        ({"post_type": "suggest"}, False),  # предложка
        ({"marked_as_ads": 1}, False),  # реклама
        ({"marked_as_ads": 0}, True),
    ],
)
def test_is_news(over: dict[str, Any], expected: bool) -> None:
    assert is_news(post_obj(**over)) is expected


def test_parse_posts_filters_dedupes_and_sorts_by_date() -> None:
    posts = parse_posts(
        [
            post_obj(1, date=100, is_pinned=1),  # закреп пришел первым, но он самый старый
            post_obj(3, date=300),
            post_obj(2, from_id=777),
            post_obj(4, date=200),
            post_obj(3, date=300, text="Правка"),  # повтор того же поста - побеждает последний
        ]
    )
    assert [(p.id, p.title) for p in posts] == [(3, "Правка"), (4, "Открытие центра"), (1, "Открытие центра")]


def test_parse_raw_reads_post_objects(tmp_path: Path) -> None:
    RawLog(tmp_path).append([post_obj(1), post_obj(2, from_id=777)])
    assert [p.id for p in parse_raw(tmp_path)] == [1]


def test_photo_prefers_orig_photo() -> None:
    att = {
        "type": "photo",
        "photo": {
            "id": 9,
            "owner_id": -GROUP,
            "orig_photo": {"url": "https://pp.example/orig.jpg", "width": 1200, "height": 675},
            "sizes": [{"type": "x", "url": "https://pp.example/x.jpg", "width": 640, "height": 360}],
        },
    }
    photo = parse_post(post_obj(attachments=[att])).photos[0]
    assert (photo.url, photo.width, photo.height) == ("https://pp.example/orig.jpg", 1200, 675)


def test_photo_with_zero_sizes_still_parsed() -> None:
    """У старых фото бывает width=0; разбор не падает, фото не теряется."""
    att = {
        "type": "photo",
        "photo": {
            "id": 9,
            "owner_id": -GROUP,
            "sizes": [{"type": "w", "url": "https://pp.example/w.jpg", "width": 0, "height": 0}],
        },
    }
    assert [p.url for p in parse_post(post_obj(attachments=[att])).photos] == ["https://pp.example/w.jpg"]


def test_photo_without_url_is_skipped_not_fatal() -> None:
    att = {"type": "photo", "photo": {"id": 9, "owner_id": -GROUP, "sizes": []}}
    post = parse_post(post_obj(attachments=[att]))
    assert post.photos == [] and post.skipped == ["photo"]


def test_repost_takes_original_and_source_name() -> None:
    original = post_obj(55, owner_id=-777, from_id=-777, text="Оригинал #тег", attachments=[])
    names = {-777: "Другая группа"}
    post = parse_post(post_obj(10, text="", attachments=[], copy_history=[original]), names)
    assert post.repost is not None
    assert (post.repost.id, post.repost.owner_id, post.repost.source_name) == (55, -777, "Другая группа")
    assert post.repost.vk_url == "https://vk.com/wall-777_55"
    assert post.title == "Оригинал #тег" and post.tags == ["тег"]  # своего текста нет - берем из оригинала


def test_repost_without_names_has_no_source_name() -> None:
    original = post_obj(55, owner_id=5, from_id=5, attachments=[])
    assert parse_post(post_obj(10, copy_history=[original])).repost.source_name is None  # type: ignore[union-attr]


def test_source_names() -> None:
    names = source_names(
        {"groups": [{"id": 5, "name": "Группа"}], "profiles": [{"id": 7, "first_name": "Иван", "last_name": "Иванов"}]}
    )
    assert names == {-5: "Группа", 7: "Иван Иванов"}


# --- Реальный ответ wall.get тестовой группы (обезличенный) ---


def test_fixture_parses_all_posts() -> None:
    data = wall()
    posts = parse_wall(data)
    assert len(posts) == len(data["items"]) == 10
    assert all(p.owner_id == -TEST_GROUP for p in posts)


def test_fixture_pinned_post_is_not_first_after_sorting() -> None:
    data = wall()
    assert data["items"][0]["is_pinned"] == 1 and data["items"][0]["id"] == 13  # VK отдает закреп первым
    posts = parse_wall(data)
    assert posts[0].id == 23  # самый новый
    pinned = [p for p in posts if p.pinned]
    assert [p.id for p in pinned] == [13]


def test_fixture_attachment_kinds() -> None:
    posts = by_id(parse_wall(wall()))
    assert len(posts[18].photos) == 6
    assert [(m.kind, m.title) for m in posts[17].media] == [("doc", "11_notes.txt")]
    assert [m.kind for m in posts[4].media] == ["video"]
    assert len(posts[16].links) == 1 and len(posts[16].photos) == 1
    assert posts[15].skipped == ["poll"] and len(posts[15].photos) == 1
    assert posts[8].skipped == ["poll"]
    assert posts[6].text == "" and posts[6].title == "" and len(posts[6].photos) == 1
    assert posts[21].photos == [] and posts[21].media == [] and posts[21].links == []


def test_fixture_photos_use_largest_size() -> None:
    for post in parse_wall(wall()):
        for photo in post.photos:
            assert photo.width > 0 and photo.height > 0
            assert photo.url.startswith("https://")
