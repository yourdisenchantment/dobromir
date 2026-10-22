from pathlib import Path

from pipeline.fetch.rawlog import RawLog
from pipeline.parse import parse_post, parse_raw
from pipeline.parse.posts import make_title
from samples import GROUP, post_event


def test_parse_post_fields() -> None:
    post = parse_post(post_event()["object"])
    assert post.title == "Открытие центра"
    assert post.tags == ["мероприятия", "Добромир"]
    assert [p.id for p in post.photos] == [1, 2]
    assert post.photos[0].url.endswith("1_w.jpg")  # самый большой размер
    assert post.photos[0].uid == f"m{GROUP}_1"
    assert [link.url for link in post.links] == ["https://example.org/a"]
    assert post.skipped == ["video"]
    assert post.pinned is False
    assert post.slug == "2026-08-06-vk101"
    assert post.vk_url == f"https://vk.com/wall-{GROUP}_101"


def test_title_truncated_on_word_boundary() -> None:
    title = make_title("слово " * 40)
    assert len(title) <= 121
    assert title.endswith("…")
    assert make_title("\n\n  \n") == ""


def test_parse_raw_filters_and_dedupes(tmp_path: Path) -> None:
    log = RawLog(tmp_path)
    log.append(
        [
            post_event(1),
            post_event(2, from_id=777),  # запись посетителя
            post_event(3, post_type="suggest"),
            {"type": "message_new", "object": {}},
            post_event(1, text="Правка"),  # повтор того же поста
        ]
    )
    posts = parse_raw(tmp_path)
    assert [(p.id, p.title) for p in posts] == [(1, "Правка")]
