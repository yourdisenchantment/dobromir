import copy
from typing import Any

from pipeline.parse import content_hash, parse_post
from samples import GROUP, photo_att, post_obj


def h(obj: dict[str, Any]) -> str:
    return content_hash(parse_post(obj))


def changed(**over: Any) -> dict[str, Any]:
    return post_obj(**over)


def test_same_post_same_hash() -> None:
    assert h(post_obj()) == h(post_obj())
    assert len(h(post_obj())) == 64


def test_text_change_changes_hash() -> None:
    assert h(post_obj()) != h(changed(text="Другой текст"))


def test_counters_do_not_change_hash() -> None:
    base = post_obj()
    noisy = post_obj(
        likes={"count": 99},
        views={"count": 1000},
        comments={"count": 5},
        reposts={"count": 3},
        reactions={"count": 7},
    )
    assert h(base) == h(noisy)


def test_pin_does_not_change_hash() -> None:
    assert h(post_obj()) == h(post_obj(is_pinned=1))


def test_photo_url_change_same_id_keeps_hash() -> None:
    """VK подписывает адреса картинок и меняет их - это не правка поста."""
    other = post_obj()
    for size in other["attachments"][0]["photo"]["sizes"]:
        size["url"] = size["url"].replace("pp.example", "sun9-1.example") + "?sign=new"
    assert h(post_obj()) == h(other)


def test_photo_replaced_changes_hash() -> None:
    other = post_obj()
    other["attachments"][0] = photo_att(77)
    assert h(post_obj()) != h(other)


def test_photo_order_changes_hash() -> None:
    """Порядок важен: первое фото - обложка."""
    other = post_obj()
    other["attachments"][0], other["attachments"][1] = other["attachments"][1], other["attachments"][0]
    assert h(post_obj()) != h(other)


def test_edited_appears_changes_hash() -> None:
    assert h(post_obj()) != h(post_obj(edited=1786003600))


def test_link_and_media_changes_change_hash() -> None:
    other = post_obj()
    other["attachments"][3] = {"type": "link", "link": {"url": "https://example.org/b", "title": "Подробнее"}}
    assert h(post_obj()) != h(other)
    other = post_obj()
    other["attachments"][2] = {"type": "video", "video": {"id": 6, "owner_id": -GROUP}}
    assert h(post_obj()) != h(other)


def test_poll_does_not_affect_hash() -> None:
    """Опрос не показываем - его правка не повод пересобирать сайт."""
    with_poll = post_obj()
    with_poll["attachments"].append({"type": "poll", "poll": {"id": 1, "question": "?", "votes": 3}})
    more_votes = copy.deepcopy(with_poll)
    more_votes["attachments"][-1]["poll"]["votes"] = 30
    assert h(with_poll) == h(more_votes)


def test_repost_original_changes_change_hash() -> None:
    orig = post_obj(55, owner_id=-777, from_id=-777, attachments=[])
    base = post_obj(10, text="", attachments=[], copy_history=[orig])
    edited_orig = copy.deepcopy(base)
    edited_orig["copy_history"][0]["text"] = "Оригинал поправили"
    assert h(base) != h(edited_orig)
    assert h(base) != h(post_obj(10, text="", attachments=[]))  # репост против пустого поста
