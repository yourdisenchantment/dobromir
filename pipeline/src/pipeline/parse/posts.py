"""Разбор поста VK в нашу модель. В сеть не ходит."""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pipeline.parse.model import Link, Photo, Post

HASHTAG = re.compile(r"#([^\s#@]+)")
TITLE_MAX = 120
POST_EVENTS = {"wall_post_new"}


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
    sizes = att.get("sizes") or []
    if not sizes and att.get("orig_photo"):
        sizes = [att["orig_photo"]]
    sizes = [s for s in sizes if s.get("url")]
    if not sizes:
        return None
    best = max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))
    return Photo(
        owner_id=att["owner_id"],
        id=att["id"],
        url=best["url"],
        width=best.get("width", 0),
        height=best.get("height", 0),
    )


def parse_post(obj: dict[str, Any]) -> Post:
    text = obj.get("text") or ""
    photos: list[Photo] = []
    links: list[Link] = []
    skipped: list[str] = []
    for att in obj.get("attachments") or []:
        kind = att.get("type", "?")
        if kind == "photo":
            photo = _photo(att["photo"])
            if photo:
                photos.append(photo)
        elif kind == "link":
            links.append(Link(url=att["link"]["url"], title=att["link"].get("title", "")))
        else:
            skipped.append(kind)
    return Post(
        owner_id=obj["owner_id"],
        id=obj["id"],
        timestamp=obj["date"],
        title=make_title(text),
        text=text,
        tags=list(dict.fromkeys(HASHTAG.findall(text))),
        pinned=bool(obj.get("is_pinned")),
        photos=photos,
        links=links,
        skipped=skipped,
    )


def iter_raw_events(raw_dir: Path) -> Iterator[dict[str, Any]]:
    """Сырые события по порядку получения."""
    for path in sorted(raw_dir.glob("events-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)


def parse_raw(raw_dir: Path) -> list[Post]:
    """Все посты из сырых событий, самые новые первыми. Повтор поста заменяет прежнюю версию.

    Берем только посты от имени самого сообщества: записи посетителей на стене в новости не идут.
    """
    posts: dict[tuple[int, int], Post] = {}
    for event in iter_raw_events(raw_dir):
        if event.get("type") not in POST_EVENTS:
            continue
        obj = event["object"]
        if obj.get("from_id") != obj.get("owner_id") or obj.get("post_type", "post") != "post":
            continue
        post = parse_post(obj)
        posts[(post.owner_id, post.id)] = post
    return sorted(posts.values(), key=lambda p: p.timestamp, reverse=True)
