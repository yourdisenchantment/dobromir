"""Склейка стадий: ответ VK -> база -> фото -> news.json.

Сверка окна, удаления, лимит сборок - P1-4; здесь только то, что нужно им всем.
"""

from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from pipeline.media.photos import download_photo
from pipeline.parse.posts import is_news, source_names
from pipeline.store.state import Change, Store


def ingest(store: Store, responses: Iterable[dict[str, Any]], now: int) -> Counter[Change]:
    """Записывает посты из ответов `wall.get`/`wall.getById` (extended=1). Чужие и рекламные пропускает."""
    changes: Counter[Change] = Counter()
    for response in responses:
        names = source_names(response)
        for obj in response.get("items") or []:
            if not is_news(obj):
                continue
            history = obj.get("copy_history") or []
            source = names.get(history[0]["owner_id"]) if history else None
            changes[store.upsert(obj, now, source)] += 1
    return changes


def download_photos(store: Store, http: httpx.Client, media_dir: Path, now: int) -> int:
    """Скачивает фото живых постов, которых еще нет. Возвращает, сколько скачано сейчас.

    Скачанное фото меняет экспорт (раньше его не было в news.json), значит и это повод собрать сайт.
    """
    count = 0
    for stored in store.posts():
        for photo in stored.post.all_photos:
            known = store.photo_info(photo)
            if known is not None and (media_dir / known[0]).is_file():
                continue
            path = download_photo(http, photo, media_dir)
            if path is None:
                continue  # сбой уже записан в лог; попробуем на следующем запуске
            with Image.open(path) as img:
                width, height = img.size  # после поворота по EXIF размеры могут поменяться местами
            store.record_photo(photo, path.relative_to(media_dir).as_posix(), width, height, now)
            count += 1
    return count
