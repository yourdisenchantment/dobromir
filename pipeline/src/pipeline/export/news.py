"""Экспорт постов в `content/news/<дата>-vk<id>/` для Astro: meta.json и фото рядом."""

import json
import os
import shutil
from pathlib import Path

from pipeline.media.photos import photo_path
from pipeline.parse.model import Post


def _place(src: Path, dst: Path) -> None:
    """Жесткая ссылка вместо копии: на хостинге лимит места. Если ФС не дает - копия."""
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def export_post(post: Post, media_dir: Path, content_dir: Path) -> Path:
    folder = content_dir / "news" / post.slug
    folder.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    for photo in post.photos:
        src = photo_path(media_dir, photo)
        if src.exists():  # недокачанное попадет в экспорт при следующем проходе
            name = f"{len(files) + 1:02d}.jpg"
            _place(src, folder / name)
            files.append(name)
    meta = {
        "title": post.title,
        "description": post.text,
        "tags": post.tags,
        "pinned": post.pinned,
        "published": post.date.isoformat(),
        "source": post.vk_url,
        "cover": files[0] if files else None,
        "photos": files,
        "links": [link.model_dump() for link in post.links],
    }
    tmp = folder / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(folder / "meta.json")
    return folder
