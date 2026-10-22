"""Отпечаток того, что пост показывает на сайте. Изменился - сайт надо пересобрать.

Входит: текст, `edited`, вложения (по идентичности, без временных адресов фото),
ссылки, документы и видео, оригинал репоста. Не входит: лайки, просмотры,
комментарии, число репостов, адреса картинок (VK их подписывает и меняет), закреп.
Порядок вложений сохраняется: от него зависит, какое фото на обложке.
"""

import hashlib
import json
from typing import Any

from pipeline.parse.model import Content, Post


def _content(c: Content) -> dict[str, Any]:
    return {
        "text": c.text,
        "photos": [f"{p.owner_id}_{p.id}" for p in c.photos],
        "links": [[link.url, link.title] for link in c.links],
        "media": [[m.kind, f"{m.owner_id}_{m.id}", m.title] for m in c.media],
    }


def content_hash(post: Post) -> str:
    """sha256 от канонического JSON показываемых полей."""
    data = {
        **_content(post),
        "edited": post.edited,
        "repost": None
        if post.repost is None
        else {"id": f"{post.repost.owner_id}_{post.repost.id}", **_content(post.repost)},
    }
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
