"""Скачивание фото поста к себе: ссылки VK временные.

Разрешение не трогаем (решение плана, разд. 8): только впекаем ориентацию и убираем EXIF/GPS.
"""

import io
import logging
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from pipeline.parse.model import Photo

log = logging.getLogger(__name__)


def clean_jpeg(data: bytes) -> bytes:
    """Поворачивает кадр по EXIF-ориентации и пересохраняет без метаданных (ICC-профиль остается)."""
    with Image.open(io.BytesIO(data)) as src:
        icc = src.info.get("icc_profile")
        img = ImageOps.exif_transpose(src)
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=90, optimize=True, icc_profile=icc)
    return out.getvalue()


def photo_path(media_dir: Path, photo: Photo) -> Path:
    return media_dir / "photos" / f"{photo.uid}.jpg"


def download_photo(http: httpx.Client, photo: Photo, media_dir: Path) -> Path | None:
    """Скачивает и чистит фото; уже скачанное пропускает. При сбое возвращает None."""
    path = photo_path(media_dir, photo)
    if path.exists():
        return path
    try:
        resp = http.get(photo.url, timeout=60)
        resp.raise_for_status()
        data = clean_jpeg(resp.content)
    except (httpx.HTTPError, OSError) as exc:
        # Адрес фото в лог не пишем: в нем подпись доступа.
        log.warning("фото %s не скачано (%s)", photo.uid, type(exc).__name__)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path
