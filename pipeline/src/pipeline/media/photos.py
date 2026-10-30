"""Фото поста к себе: ссылки VK временные, поэтому храним файлы.

Храним не исходник, а копии для показа (решено 2026-10-25): WebP с длинной стороной до
1600 px - для окна и страницы новости, до 800 px - для карточки. Больше исходного не
увеличиваем: фото до 800 px - один файл на оба случая. Ориентация впекается в пиксели,
EXIF/GPS не переносятся (ICC-профиль остается).
"""

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image, ImageOps

from pipeline.parse.model import DISPLAY_MAX, Photo

log = logging.getLogger(__name__)

FULL_MAX = DISPLAY_MAX
PREVIEW_MAX = 800
PREVIEW_SUFFIX = "-800"
WEBP_QUALITY = 80


@dataclass(frozen=True)
class Rendition:
    file: str  # путь относительно каталога media/
    width: int
    height: int


@dataclass(frozen=True)
class PhotoFiles:
    full: Rendition  # окно и страница новости
    preview: Rendition  # карточка; у маленьких фото - тот же файл, что full

    @property
    def files(self) -> list[str]:
        return list(dict.fromkeys([self.full.file, self.preview.file]))


def fit(size: tuple[int, int], limit: int) -> tuple[int, int]:
    """Размер, вписанный по длинной стороне в limit; меньше limit - без изменений."""
    width, height = size
    longest = max(width, height)
    if longest <= limit:
        return size
    scale = limit / longest
    return max(1, round(width * scale)), max(1, round(height * scale))


def render(data: bytes) -> list[tuple[str, bytes, int, int]]:
    """Копии для показа: (суффикс имени, WebP, ширина, высота). Первая - полная.

    Raises:
        OSError: данные - не картинка (PIL.UnidentifiedImageError - подкласс OSError).
    """
    with Image.open(io.BytesIO(data)) as src:
        icc = src.info.get("icc_profile")
        img = ImageOps.exif_transpose(src).convert("RGB")
    out: list[tuple[str, bytes, int, int]] = []
    sizes = [("", fit(img.size, FULL_MAX))]
    if max(img.size) > PREVIEW_MAX:
        sizes.append((PREVIEW_SUFFIX, fit(img.size, PREVIEW_MAX)))
    for suffix, size in sizes:
        scaled = img if size == img.size else img.resize(size, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        scaled.save(buf, "WEBP", quality=WEBP_QUALITY, icc_profile=icc)
        out.append((suffix, buf.getvalue(), *size))
    return out


def save_photo(media_dir: Path, photo: Photo, data: bytes) -> PhotoFiles:
    """Пишет копии для показа (каждую атомарно) и возвращает их описание.

    Raises:
        OSError: данные - не картинка или не записать файл.
    """
    renditions: list[Rendition] = []
    for suffix, body, width, height in render(data):
        rel = f"photos/{photo.uid}{suffix}.webp"
        path = media_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        renditions.append(Rendition(rel, width, height))
    full = renditions[0]
    return PhotoFiles(full=full, preview=renditions[1] if len(renditions) > 1 else full)


def _is_safe_photo_url(url: str) -> bool:
    """URL фото должен быть HTTPS. Проверка на внутренние адреса - защита от SSRF."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return False
    # Блокируем внутренние адреса (SSRF-защита)
    is_internal = (
        host in ("localhost", "127.0.0.1", "0.0.0.0")
        or host.startswith("10.")
        or host.startswith("192.168.")
        or host.startswith("172.")
    )
    return not is_internal


def fetch_photo(http: httpx.Client, photo: Photo) -> bytes | None:
    """Скачивает фото из VK. При сбое - None (попробуем на следующем запуске)."""
    if not _is_safe_photo_url(photo.url):
        log.warning("фото %s пропущено: недопустимый адрес", photo.uid)
        return None
    try:
        resp = http.get(photo.url, timeout=60, follow_redirects=False)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        # Адрес фото в лог не пишем: в нем подпись доступа. Код ответа - пишем: по нему видно,
        # временный ли сбой (429, 5xx) или ссылка больше не годится (403, 404).
        status = f" {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else ""
        log.warning("фото %s не скачано (%s%s)", photo.uid, type(exc).__name__, status)
        return None
    # Защита от OOM: фото VK не бывают больше 10 МБ
    if len(resp.content) > 10 * 1024 * 1024:
        log.warning("фото %s слишком большое (%d байт), пропущено", photo.uid, len(resp.content))
        return None
    return resp.content
