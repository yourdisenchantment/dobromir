"""Склейка стадий: ответ VK -> база -> фото -> news.json.

Сверка окна, удаления, лимит сборок - P1-4; здесь только то, что нужно им всем.
"""

import logging
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

from pipeline.media.photos import fetch_photo, save_photo
from pipeline.parse.posts import is_news, source_names
from pipeline.store.state import Change, Store

log = logging.getLogger(__name__)


def ingest(store: Store, responses: Iterable[dict[str, Any]], now: int, since: int | None = None) -> Counter[Change]:
    """Записывает посты из ответов `wall.get`/`wall.getById` (extended=1). Чужие и рекламные пропускает.

    since - не записывать посты с датой публикации раньше (срок хранения новостей): иначе
    окно опроса каждый час возвращало бы в базу уже удаленные по сроку.
    """
    changes: Counter[Change] = Counter()
    for response in responses:
        names = source_names(response)
        for obj in response.get("items") or []:
            if not is_news(obj) or (since is not None and int(obj.get("date") or 0) < since):
                continue
            history = obj.get("copy_history") or []
            source = names.get(history[0]["owner_id"]) if history else None
            changes[store.upsert(obj, now, source)] += 1
    return changes


def download_photos(store: Store, http: httpx.Client, media_dir: Path, now: int) -> int:
    """Готовит фото живых постов, которых еще нет. Возвращает, сколько готово сейчас.

    Запись старого вида (исходный JPEG до 2026-10-25) пересчитывается из своего файла, без
    VK: ссылки VK к этому времени могли истечь; после пересчета старый файл удаляется.
    Новое фото меняет экспорт (раньше его не было в news.json), значит и это повод собрать сайт.
    """
    count = 0
    for stored in store.posts():
        for photo in stored.post.all_photos:
            record = store.photo_info(photo)
            if (
                record is not None
                and record.preview is not None
                and all((media_dir / name).is_file() for name in record.files)
            ):
                continue  # готово
            old = media_dir / record.file if record is not None and record.preview is None else None
            data = old.read_bytes() if old is not None and old.is_file() else fetch_photo(http, photo)
            if data is None:
                continue  # сбой уже записан в лог; попробуем на следующем запуске
            try:
                files = save_photo(media_dir, photo, data)
            except OSError as exc:
                log.warning("фото %s не сохранено (%s)", photo.uid, type(exc).__name__)
                continue
            store.record_photo(photo, files, now)
            if old is not None and old.name not in {Path(f).name for f in files.files}:
                old.unlink(missing_ok=True)  # запись уже указывает на новые файлы
            count += 1
    return count
