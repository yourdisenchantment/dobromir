"""Чистка картинок, которые больше 30 дней не нужны ни одному живому посту (P2-2).

Срок считается от `photos.last_used_at`: его обновляет каждый экспорт news.json для фото
живых постов. Две защиты от ошибки в этом учете: фото, которое прямо сейчас есть у живого
поста, не удаляется при любой дате; удаляются только файлы вида `photos/<uid>[-800].webp`
(или `.jpg` старого вида) внутри каталога media, не ссылки. У фото до двух файлов - копия
для окна и превью; удаляются оба. Сначала стирается запись в базе, потом файл: оборвется посередине -
останется лишний файл, но не битая картинка на сайте.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.store.state import Store

log = logging.getLogger("pipeline")

MEDIA_KEEP_DAYS = 30
PHOTO_FILE = re.compile(r"^photos/[0-9m]+_[0-9]+(-800)?\.(webp|jpg)$")


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
    for owner_id, photo_id, record in store.stale_photos(used_before):
        if (owner_id, photo_id) in in_use:
            result.in_use += 1
            continue
        refused = [name for name in record.files if not _ours(media_dir / name, name, photos_dir)]
        if refused:
            result.refused.extend(refused)  # запись и все ее файлы не трогаем
            continue
        result.removed.extend(record.files)
        if dry_run:
            continue
        store.forget_photo(owner_id, photo_id)
        for name in record.files:
            try:
                (media_dir / name).unlink(missing_ok=True)
            except OSError as exc:
                log.warning("файл %s не удален (%s); запись о нем уже убрана", name, type(exc).__name__)
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


def _ours(path: Path, name: str, photos_dir: Path) -> bool:
    """Наш файл фото: имя по образцу, лежит прямо в media/photos, не ссылка."""
    return bool(PHOTO_FILE.match(name)) and not path.is_symlink() and path.resolve().parent == photos_dir
