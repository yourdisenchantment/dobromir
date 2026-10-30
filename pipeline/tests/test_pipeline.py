"""Сквозные проверки: ответ VK -> база -> фото -> news.json."""

import io
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from pipeline.export import build_news, write_news
from pipeline.media.photos import fit, render
from pipeline.parse import Photo
from pipeline.store import Change, Store, open_db
from pipeline.sync import download_photos, ingest
from samples import GROUP, post_obj

FIXTURE = Path(__file__).parent / "fixtures" / "wall_get_antarctic.json"
NOW = 1786100000


def jpeg(orientation: int | None = None, size: tuple[int, int] = (40, 20)) -> bytes:
    img = Image.new("RGB", size, "red")  # по умолчанию широкая картинка
    exif = Image.Exif()
    exif[0x0112] = orientation or 1
    exif[0x010F] = "SecretCamera"
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    return out.getvalue()


def photo_http(status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=jpeg(6) if status == 200 else b"")

    return httpx.Client(transport=httpx.MockTransport(handler))


def store_at(tmp_path: Path) -> Store:
    return Store(open_db(tmp_path / "data" / "db" / "dobromir.sqlite"))


def response(*items: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"count": len(items), "items": list(items), **extra}


def test_render_bakes_orientation_and_strips_exif() -> None:
    [(suffix, body, width, height)] = render(jpeg(orientation=6))  # 6 = повернуть на 90
    assert suffix == "" and (width, height) == (20, 40)
    with Image.open(io.BytesIO(body)) as img:
        assert img.format == "WEBP" and img.size == (20, 40)
        assert not img.getexif()
    assert b"SecretCamera" not in body


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((4000, 3000), [("", 1600, 1200), ("-800", 800, 600)]),  # крупное - обе копии уменьшены
        ((3000, 4000), [("", 1200, 1600), ("-800", 600, 800)]),  # портрет - по длинной стороне
        ((1600, 900), [("", 1600, 900), ("-800", 800, 450)]),  # ровно 1600 - без изменений
        ((1200, 900), [("", 1200, 900), ("-800", 800, 600)]),  # между 800 и 1600 - не увеличиваем
        ((801, 400), [("", 801, 400), ("-800", 800, 400)]),
        ((800, 600), [("", 800, 600)]),  # до 800 - один файл на оба случая
        ((300, 200), [("", 300, 200)]),
        ((1000, 3000), [("", 533, 1600), ("-800", 267, 800)]),  # высокий плакат
    ],
)
def test_render_sizes_never_upscale(size: tuple[int, int], expected: list[tuple[str, int, int]]) -> None:
    out = render(jpeg(size=size))
    assert [(s, w, h) for s, _, w, h in out] == expected
    for _, body, w, h in out:
        with Image.open(io.BytesIO(body)) as img:
            assert img.size == (w, h)


def test_fit_keeps_small_sizes() -> None:
    assert fit((10, 10), 800) == (10, 10) and fit((8000, 1), 800) == (800, 1)


def test_old_jpeg_record_is_converted_locally(tmp_path: Path) -> None:
    """Запись старого вида (исходный JPEG) пересчитывается из файла, без VK; JPEG удаляется."""
    store = store_at(tmp_path)
    media = tmp_path / "media"
    ingest(store, [response(post_obj(101, attachments=post_obj()["attachments"][:1]))], NOW)
    [photo] = store.posts()[0].post.all_photos
    old = media / "photos" / f"{photo.uid}.jpg"
    old.parent.mkdir(parents=True)
    old.write_bytes(jpeg(size=(2000, 1000)))
    # Так записи выглядели до миграции 0002: только file_name, width, height.
    store._db.execute(
        "INSERT INTO photos (owner_id, id, file_name, width, height, downloaded_at, last_used_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (photo.owner_id, photo.id, f"photos/{photo.uid}.jpg", 2000, 1000, NOW, NOW),
    )
    store._db.commit()
    assert build_news(store, media, NOW)["posts"][0]["photos"] == []  # старый вид не экспортируется
    with photo_http(404) as http:  # VK недоступен - пересчет все равно идет из файла
        assert download_photos(store, http, media, NOW) == 1
    [exported] = build_news(store, media, NOW)["posts"][0]["photos"]
    assert exported["file"] == f"photos/{photo.uid}.webp" and (exported["width"], exported["height"]) == (1600, 800)
    assert exported["preview"] == {"file": f"photos/{photo.uid}-800.webp", "width": 800, "height": 400}
    assert not old.exists() and (media / exported["file"]).is_file()
    store.close()


def test_broken_image_skipped(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    ingest(store, [response(post_obj(101))], NOW)
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>")))
    with http:
        assert download_photos(store, http, tmp_path / "media", NOW) == 0
    assert build_news(store, tmp_path / "media", NOW)["posts"][0]["photos"] == []
    store.close()


def test_failed_photo_logs_status_without_url(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Код ответа - чтобы отличить временный сбой VK от мертвой ссылки; адреса (подписи) - нет."""
    store = store_at(tmp_path)
    ingest(store, [response(post_obj(101))], NOW)
    with photo_http(403) as http, caplog.at_level("WARNING"):
        assert download_photos(store, http, tmp_path / "media", NOW) == 0
    assert "HTTPStatusError 403" in caplog.text and "http" not in caplog.text.replace("HTTPStatusError", "")
    store.close()


def test_end_to_end_news_json(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    media = tmp_path / "site" / "media"
    changes = ingest(store, [response(post_obj(101), post_obj(102, from_id=777))], NOW)
    assert changes == {Change.NEW: 1}  # пост посетителя отброшен
    with photo_http() as http:
        assert download_photos(store, http, media, NOW) == 2
        assert download_photos(store, http, media, NOW) == 0  # уже скачано
    news = build_news(store, media, NOW)
    path = tmp_path / "data" / "export" / "news.json"
    assert write_news(path, news) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 2
    [post] = data["posts"]
    assert post["id"] == 101 and post["slug"] == "2026-08-06-vk101"
    assert post["title"] == "Открытие центра" and post["tags"] == ["мероприятия", "Добромир"]
    assert post["date"] == "2026-08-06T10:06:40+03:00"  # Симферополь
    assert post["edited_date"] is None
    assert post["source_url"] == f"https://vk.com/wall-{GROUP}_101"
    assert [p["file"] for p in post["photos"]] == [f"photos/m{GROUP}_1.webp", f"photos/m{GROUP}_2.webp"]
    assert post["photos"][0]["width"] == 20 and post["photos"][0]["height"] == 40  # повернуто по EXIF
    # Маленькое фото: превью - тот же файл.
    assert post["photos"][0]["preview"] == {"file": f"photos/m{GROUP}_1.webp", "width": 20, "height": 40}
    assert post["media"] == [{"kind": "video", "title": ""}]
    assert post["links"] == [{"url": "https://example.org/a", "title": "Подробнее"}]
    assert (media / post["photos"][0]["file"]).is_file()
    store.close()


def test_failed_photo_download_is_skipped_not_fatal(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    ingest(store, [response(post_obj(101))], NOW)
    with photo_http(404) as http:
        assert download_photos(store, http, tmp_path / "media", NOW) == 0
    [post] = build_news(store, tmp_path / "media", NOW)["posts"]
    assert post["photos"] == []  # не скачано - в экспорт не попало
    store.close()


def test_write_news_reports_real_changes_only(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    ingest(store, [response(post_obj(101, attachments=[]))], NOW)
    path = tmp_path / "news.json"
    assert write_news(path, build_news(store, tmp_path, NOW)) is True
    assert write_news(path, build_news(store, tmp_path, NOW + 3600)) is False  # только generated_at другое
    ingest(store, [response(post_obj(101, attachments=[], text="Правка"))], NOW)
    assert write_news(path, build_news(store, tmp_path, NOW)) is True
    assert not list(tmp_path.glob("*.tmp"))
    store.close()


def test_deleted_posts_not_exported(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    ingest(store, [response(post_obj(1, attachments=[]), post_obj(2, attachments=[]))], NOW)
    store.mark_deleted([(-GROUP, 1)], NOW)
    assert [p["id"] for p in build_news(store, tmp_path, NOW)["posts"]] == [2]
    store.close()


def test_edited_date_only_when_differs(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    ingest(
        store,
        [
            response(
                post_obj(1, attachments=[], date=1786000000, edited=1786000030),  # в ту же минуту
                post_obj(2, attachments=[], date=1786000000, edited=1786200000),  # через два дня
            )
        ],
        NOW,
    )
    by_id = {p["id"]: p for p in build_news(store, tmp_path, NOW)["posts"]}
    assert by_id[1]["edited_date"] == "2026-08-06T10:07:10+03:00"
    assert by_id[2]["edited_date"] == "2026-08-08T17:40:00+03:00"
    store.close()


def test_repost_exported_with_source(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    original = post_obj(55, owner_id=-777, from_id=-777, text="Оригинал", attachments=[])
    ingest(
        store,
        [
            response(
                post_obj(10, text="", attachments=[], copy_history=[original]), groups=[{"id": 777, "name": "Соседи"}]
            )
        ],
        NOW,
    )
    [post] = build_news(store, tmp_path, NOW)["posts"]
    assert post["repost"]["source_name"] == "Соседи"
    assert post["repost"]["source_url"] == "https://vk.com/wall-777_55"
    assert post["repost"]["text"] == "Оригинал" and post["title"] == "Оригинал"
    store.close()


def test_rebuild_from_raw_json_gives_identical_news(tmp_path: Path) -> None:
    """База - источник правды: из raw_json строится тот же news.json, без похода в VK."""
    store = store_at(tmp_path)
    ingest(store, [json.loads(FIXTURE.read_text(encoding="utf-8"))], NOW)
    first = build_news(store, tmp_path, NOW)
    raws = [sp.raw for sp in store.posts()]
    store.close()

    store2 = Store(open_db(tmp_path / "fresh.sqlite"))
    ingest(store2, [response(*raws, groups=[{"id": 242263522, "name": "Antarctic test"}])], NOW)
    assert build_news(store2, tmp_path, NOW) == first
    store2.close()


def test_news_json_has_no_secrets(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["items"][1]["attachments"][0]["photo"]["access_key"] = "SECRET-ACCESS-KEY"
    ingest(store, [data], NOW)
    text = json.dumps(build_news(store, tmp_path, NOW), ensure_ascii=False)
    assert "SECRET-ACCESS-KEY" not in text and "access_key" not in text
    # Временные адреса фото VK в экспорт не идут: у фото только файл и размеры.
    for post in json.loads(text)["posts"]:
        for photo in post["photos"]:
            assert set(photo) == {"file", "width", "height", "preview"}
    store.close()


def test_fixture_end_to_end(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    changes = ingest(store, [json.loads(FIXTURE.read_text(encoding="utf-8"))], NOW)
    assert changes == {Change.NEW: 10}
    posts = build_news(store, tmp_path, NOW)["posts"]
    assert [p["id"] for p in posts] == [23, 21, 18, 17, 16, 15, 13, 8, 6, 4]
    assert [p["id"] for p in posts if p["pinned"]] == [13]
    store.close()


def test_open_db_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "x.sqlite"
    open_db(db).close()
    conn = open_db(db)
    from pipeline.store.db import migrations

    versions = [r[0] for r in conn.execute("SELECT version FROM schema_version")]
    assert versions == list(range(1, len(migrations()) + 1))  # каждая миграция один раз
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"posts", "photos", "meta", "schema_version"} <= tables
    conn.close()


def test_migration_failure_leaves_no_partial_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.store import db as dbmod

    good = dbmod.migrations()
    bad = (len(good) + 1, "CREATE TABLE t2 (x INTEGER);\nCREATE TABLE ошибка (;")
    monkeypatch.setattr(dbmod, "migrations", lambda: [*good, bad])
    conn = sqlite3.connect(tmp_path / "y.sqlite")
    with pytest.raises(sqlite3.Error):
        dbmod.migrate(conn)
    assert dbmod.schema_version(conn) == len(good)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 't2'").fetchone() is None
    conn.close()


def test_migration_0002_keeps_old_photo_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """База версии 1 со скачанными JPEG поднимается до 2: записи целы, превью пустое (ждет пересчета)."""
    from pipeline.store import db as dbmod

    good = dbmod.migrations()
    db = tmp_path / "z.sqlite"
    monkeypatch.setattr(dbmod, "migrations", lambda: good[:1])
    conn = dbmod.open_db(db)
    conn.execute(
        "INSERT INTO photos (owner_id, id, file_name, width, height, downloaded_at, last_used_at)"
        " VALUES (-1, 5, 'photos/m1_5.jpg', 900, 600, 1, 1)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(dbmod, "migrations", lambda: good)
    store = Store(dbmod.open_db(db))
    record = store.photo_info(Photo(owner_id=-1, id=5, url="https://pp.example/x.jpg", width=1, height=1))
    assert record is not None and record.file == "photos/m1_5.jpg" and record.preview is None
    store.close()
