import io
from pathlib import Path

import httpx
from PIL import Image

from pipeline.fetch.rawlog import RawLog
from pipeline.media.photos import clean_jpeg
from pipeline.settings import DataDirs
from pipeline.sync import process
from samples import GROUP, post_obj


def jpeg(orientation: int | None = None) -> bytes:
    img = Image.new("RGB", (40, 20), "red")  # широкая картинка
    exif = Image.Exif()
    exif[0x0112] = orientation or 1
    exif[0x010F] = "SecretCamera"
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    return out.getvalue()


def test_clean_jpeg_bakes_orientation_and_strips_exif() -> None:
    cleaned = clean_jpeg(jpeg(orientation=6))  # 6 = повернуть на 90
    with Image.open(io.BytesIO(cleaned)) as img:
        assert img.size == (20, 40)
        assert not img.getexif()
    assert b"SecretCamera" not in cleaned


def dirs_for(tmp_path: Path) -> DataDirs:
    return DataDirs(root=tmp_path / "data")


def media_for(tmp_path: Path) -> Path:
    """Картинки живут в папке сайта, отдельно от каталога данных."""
    return tmp_path / "site" / "media"


def photo_http() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=jpeg(6))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_process_exports_news_folder(tmp_path: Path) -> None:
    dirs = dirs_for(tmp_path)
    RawLog(dirs.raw).append([post_obj(101)])
    with photo_http() as http:
        assert process(dirs, media_for(tmp_path), http) == 1
        assert process(dirs, media_for(tmp_path), http) == 1  # повторный проход ничего не ломает
    folder = dirs.content / "news" / "2026-08-06-vk101"
    import json

    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["title"] == "Открытие центра"
    assert meta["photos"] == ["01.jpg", "02.jpg"] and meta["cover"] == "01.jpg"
    assert meta["tags"] == ["мероприятия", "Добромир"]
    assert meta["source"] == f"https://vk.com/wall-{GROUP}_101"
    assert (folder / "01.jpg").stat().st_size > 0


def test_failed_photo_download_is_skipped_not_fatal(tmp_path: Path) -> None:
    dirs = dirs_for(tmp_path)
    RawLog(dirs.raw).append([post_obj(101)])
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    process(dirs, media_for(tmp_path), http)
    meta = (dirs.content / "news" / "2026-08-06-vk101" / "meta.json").read_text(encoding="utf-8")
    assert '"cover": null' in meta
