"""Экспорт новостей в один `news.json`, который читает сборка сайта. Формат - docs/content-contract.md."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline.parse.model import LOCAL_TZ, Content, Photo, Post
from pipeline.store.state import Store

FORMAT_VERSION = 1


def _iso(ts: int | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, LOCAL_TZ).isoformat()


class _Photos:
    """Фото для экспорта: только скачанные и реально лежащие в media/."""

    def __init__(self, store: Store, media_dir: Path) -> None:
        self._store = store
        self._media = media_dir
        self.used: list[Photo] = []

    def __call__(self, photos: list[Photo]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for photo in photos:
            info = self._store.photo_info(photo)
            if info is None or not (self._media / info[0]).is_file():
                continue  # не скачано - покажется после следующего скачивания
            file_name, width, height = info
            out.append({"file": file_name, "width": width, "height": height})
            self.used.append(photo)
        return out


def _content(c: Content, photos: _Photos) -> dict[str, Any]:
    return {
        "text": c.text,
        "photos": photos(c.photos),
        "links": [{"url": link.url, "title": link.title} for link in c.links],
        "media": [{"kind": m.kind, "title": m.title} for m in c.media],
    }


def _post(post: Post, photos: _Photos) -> dict[str, Any]:
    edited = post.edited if post.edited and _iso(post.edited) != _iso(post.timestamp) else None
    item: dict[str, Any] = {
        "id": post.id,
        "slug": post.slug,
        "title": post.title,
        "date": _iso(post.timestamp),
        "edited_date": _iso(edited),
        "pinned": post.pinned,
        "tags": post.tags,
        "source_url": post.vk_url,
        **_content(post, photos),
        "repost": None,
    }
    if post.repost is not None:
        item["repost"] = {
            "source_name": post.repost.source_name,
            "source_url": post.repost.vk_url,
            "date": _iso(post.repost.timestamp),
            **_content(post.repost, photos),
        }
    return item


def build_news(store: Store, media_dir: Path, now: int) -> dict[str, Any]:
    """Живые посты, новые первыми. Попутно отмечает использованные фото (для чистки, P2-2)."""
    photos = _Photos(store, media_dir)
    posts = [_post(sp.post, photos) for sp in store.posts()]
    store.touch_photos(photos.used, now)
    return {"version": FORMAT_VERSION, "generated_at": _iso(now), "posts": posts}


def write_news(path: Path, news: dict[str, Any]) -> bool:
    """Атомарная запись: сборка никогда не увидит недописанный файл. Возвращает, изменился ли файл.

    `generated_at` при сравнении не учитывается - иначе файл менялся бы на каждом запуске.
    """
    body = {k: v for k, v in news.items() if k != "generated_at"}
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if {k: v for k, v in old.items() if k != "generated_at"} == body:
                return False
        except ValueError:
            pass  # битый файл - перезапишем
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(news, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return True
