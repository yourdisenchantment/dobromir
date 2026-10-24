"""Чистка картинок, которые больше 30 дней не нужны ни одному живому посту (P2-2).

Срок считается от `photos.last_used_at`: его обновляет каждый экспорт news.json для фото
живых постов. Две защиты от ошибки в этом учете: фото, которое прямо сейчас есть у живого
поста, не удаляется при любой дате; удаляется только файл вида `photos/<uid>.jpg` внутри
каталога media, не ссылка. Сначала стирается запись в базе, потом файл: оборвется посередине -
останется лишний файл, но не битая картинка на сайте.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.store.state import Store

log = logging.getLogger("pipeline")

MEDIA_KEEP_DAYS = 30
PHOTO_FILE = re.compile(r"^photos/[0-9m]+_[0-9]+\.jpg$")


@dataclass
class CleanupResult:
    removed: list[str] = field(default_factory=list)  # файлы относительно media/ (в dry_run - удалились бы)
    in_use: int = 0  # срок вышел, но фото есть у живого поста - оставлено
    refused: list[str] = field(default_factory=list)  # имя или место не наше - не тронуто


def cleanup_media(
    store: Store, media_dir: Path, now: int, *, days: int = MEDIA_KEEP_DAYS, dry_run: bool = False
) -> CleanupResult:
    """Удаляет фото, не использованные дольше days дней. dry_run - только показать."""
    result = CleanupResult()
    used_before = now - days * 86400
    in_use = {(p.owner_id, p.id) for sp in store.posts() for p in sp.post.all_photos}
    photos_dir = (media_dir / "photos").resolve()
    for owner_id, photo_id, file_name in store.stale_photos(used_before):
        if (owner_id, photo_id) in in_use:
            result.in_use += 1
            continue
        path = media_dir / file_name
        if not PHOTO_FILE.match(file_name) or path.is_symlink() or path.resolve().parent != photos_dir:
            result.refused.append(file_name)
            continue
        result.removed.append(file_name)
        if dry_run:
            continue
        store.forget_photo(owner_id, photo_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("файл %s не удален (%s); запись о нем уже убрана", file_name, type(exc).__name__)
    if result.in_use:
        # Живой пост с давно не отмеченным фото - значит, экспорт не отмечал его; стоит посмотреть.
        log.warning("фото со старой отметкой у живых постов: %s - оставлены", result.in_use)
    if result.refused:
        log.warning("чужие имена в базе фото, не тронуты: %s", ", ".join(result.refused))
    log.info(
        "чистка медиа%s: %s %s",
        " (пробно)" if dry_run else "",
        "удалились бы" if dry_run else "удалено",
        len(result.removed),
    )
    return result
