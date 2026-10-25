"""Чистка картинок, на которые больше не ссылается ни один пост в базе (P2-2).

С 2026-10-26 в базе только новости за срок хранения (NEWS_RETENTION_DAYS): пост старше
удаляется целиком, и его фото становятся ничьими. Пост, удаленный в VK, остается в базе
помеченным до конца срока - его фото тоже остаются: вернут пост в группу - вернется и он.

Защита: удаляются только файлы вида `photos/<uid>[-800].webp` (или `.jpg` старого вида)
прямо в каталоге media/photos и не ссылки. У фото до двух файлов - копия для окна и
превью; удаляются оба. Сначала стирается запись в базе, потом файлы: оборвется
посередине - останется лишний файл, но не битая картинка на сайте.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.store.state import Store

log = logging.getLogger("pipeline")

PHOTO_FILE = re.compile(r"^photos/[0-9m]+_[0-9]+(-800)?\.(webp|jpg)$")


@dataclass
class CleanupResult:
    removed: list[str] = field(default_factory=list)  # файлы относительно media/ (в dry_run - удалились бы)
    refused: list[str] = field(default_factory=list)  # имя или место не наше - не тронуто


def cleanup_media(store: Store, media_dir: Path, *, dry_run: bool = False) -> CleanupResult:
    """Удаляет фото, на которые не ссылается ни один пост в базе. dry_run - только показать."""
    result = CleanupResult()
    referenced = {(p.owner_id, p.id) for sp in store.posts(include_deleted=True) for p in sp.post.all_photos}
    photos_dir = (media_dir / "photos").resolve()
    for owner_id, photo_id, record in store.photo_records():
        if (owner_id, photo_id) in referenced:
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
    if result.refused:
        log.warning("чужие имена в базе фото, не тронуты: %s", ", ".join(result.refused))
    if result.removed:
        log.info(
            "чистка медиа%s: %s %s",
            " (пробно)" if dry_run else "",
            "удалились бы" if dry_run else "удалено файлов",
            len(result.removed),
        )
    return result


def _ours(path: Path, name: str, photos_dir: Path) -> bool:
    """Наш файл фото: имя по образцу, лежит прямо в media/photos, не ссылка."""
    return bool(PHOTO_FILE.match(name)) and not path.is_symlink() and path.resolve().parent == photos_dir
