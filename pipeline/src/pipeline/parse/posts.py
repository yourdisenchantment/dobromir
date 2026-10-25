"""Разбор постов VK (`wall.get`, `wall.getById`) в нашу модель. В сеть не ходит."""

import re
from collections.abc import Iterable
from typing import Any

from pipeline.parse.model import DISPLAY_MAX, Link, Photo, Post, Repost, VkMedia

HASHTAG = re.compile(r"#([^\s#@]+)")
TITLE_MAX = 120
MEDIA_KINDS = ("doc", "video")


def make_title(text: str) -> str:
    """Первая непустая строка; если длиннее лимита - обрезка по слову с многоточием."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            break
    else:
        return ""
    if len(line) <= TITLE_MAX:
        return line
    return line[:TITLE_MAX].rsplit(" ", 1)[0].rstrip(",.;:- ") + "…"


def _photo(att: dict[str, Any]) -> Photo | None:
    """Самый маленький из размеров VK (`orig_photo` и `sizes`), которого хватает на копию для
    показа (DISPLAY_MAX по длинной стороне); если такого нет - самый большой.

    Оригинал (`orig_photo`) бывает в несколько мегабайт, а хранится все равно копия до 1600 px:
    качать его, когда есть `w` 2560 px, - лишний трафик и время (решено 2026-10-25).
    """
    candidates = [s for s in [att.get("orig_photo"), *(att.get("sizes") or [])] if s and s.get("url")]
    if not candidates:
        return None

    def area(s: dict[str, Any]) -> int:
        return (s.get("width") or 0) * (s.get("height") or 0)

    enough = [s for s in candidates if max(s.get("width") or 0, s.get("height") or 0) >= DISPLAY_MAX]
    best = min(enough, key=area) if enough else max(candidates, key=area)
    return Photo(
        owner_id=att["owner_id"],
        id=att["id"],
        url=best["url"],
        width=best.get("width") or 0,
        height=best.get("height") or 0,
    )


def _content_fields(obj: dict[str, Any]) -> dict[str, Any]:
    photos: list[Photo] = []
    links: list[Link] = []
    media: list[VkMedia] = []
    skipped: list[str] = []
    for att in obj.get("attachments") or []:
        kind = att.get("type", "?")
        body = att.get(kind) or {}
        if kind == "photo":
            photo = _photo(body)
            if photo:
                photos.append(photo)
            else:
                skipped.append(kind)
        elif kind == "link" and body.get("url"):
            links.append(Link(url=body["url"], title=body.get("title") or ""))
        elif kind in MEDIA_KINDS and "id" in body and "owner_id" in body:
            media.append(VkMedia(kind=kind, owner_id=body["owner_id"], id=body["id"], title=body.get("title") or ""))
        else:
            skipped.append(kind)
    return {
        "owner_id": obj["owner_id"],
        "id": obj["id"],
        "timestamp": obj["date"],
        "text": obj.get("text") or "",
        "photos": photos,
        "links": links,
        "media": media,
        "skipped": skipped,
    }


def source_names(response: dict[str, Any]) -> dict[int, str]:
    """Имена авторов из ответа с extended=1: ключ - owner_id (у групп со знаком минус)."""
    names: dict[int, str] = {}
    for group in response.get("groups") or []:
        names[-int(group["id"])] = str(group.get("name") or "")
    for user in response.get("profiles") or []:
        names[int(user["id"])] = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    return names


def parse_post(obj: dict[str, Any], names: dict[int, str] | None = None) -> Post:
    """Пост VK в модель. Репост - первый элемент `copy_history`: это сам оригинал."""
    fields = _content_fields(obj)
    repost = None
    history = obj.get("copy_history") or []
    if history:
        original = _content_fields(history[0])
        repost = Repost(**original, source_name=(names or {}).get(original["owner_id"]))
    text = fields["text"]
    # Если у репоста нет своего текста, заголовок и теги - из оригинала.
    title_source = text or (repost.text if repost else "")
    return Post(
        **fields,
        edited=obj.get("edited"),
        title=make_title(title_source),
        tags=list(dict.fromkeys(HASHTAG.findall(title_source))),
        pinned=bool(obj.get("is_pinned")),
        repost=repost,
    )


def is_news(obj: dict[str, Any]) -> bool:
    """В новости идут только обычные посты от имени самого сообщества, без рекламы."""
    return (
        obj.get("from_id") == obj.get("owner_id")
        and obj.get("post_type", "post") == "post"
        and not obj.get("marked_as_ads")
    )


def parse_posts(items: Iterable[dict[str, Any]], names: dict[int, str] | None = None) -> list[Post]:
    """Новости из списка постов: фильтр, без повторов (последняя версия побеждает), новые первыми.

    Сортировка по дате публикации, а не по порядку VK: закрепленный пост VK отдает первым,
    даже если он старый (проверено на тестовой группе 2026-10-23).
    """
    posts: dict[tuple[int, int], Post] = {}
    for obj in items:
        if is_news(obj):
            post = parse_post(obj, names)
            posts[(post.owner_id, post.id)] = post
    return sorted(posts.values(), key=lambda p: (p.timestamp, p.id), reverse=True)


def parse_wall(response: dict[str, Any]) -> list[Post]:
    """Ответ `wall.get` (лучше с extended=1 - тогда у репостов есть имя источника)."""
    return parse_posts(response.get("items") or [], source_names(response))
