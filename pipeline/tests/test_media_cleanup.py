"""Чистка медиа: срок 30 дней, защита фото живых постов, белый список, пробный режим, воркер."""

import io
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fakevk import FakeWall
from pipeline.media.cleanup import cleanup_media
from pipeline.parse import Photo
from pipeline.settings import Settings, load_settings
from pipeline.store import Store, open_db
from pipeline.worker import EXIT_OK, run_worker
from samples import GROUP, photo_att, post_obj

TZ = ZoneInfo("Europe/Simferopol")
DAY = 86400
NOW = int(datetime(2026, 10, 24, 4, 0, tzinfo=TZ).timestamp())


def setup(tmp_path: Path) -> tuple[Store, Path]:
    """Пост 101 с фото 1 и 2, пост 102 с фото 3; файлы скачаны, отметка - сейчас."""
    store = Store(open_db(tmp_path / "db.sqlite"))
    media = tmp_path / "media"
    store.upsert(post_obj(101, attachments=[photo_att(1), photo_att(2)]), NOW)
    store.upsert(post_obj(102, attachments=[photo_att(3)]), NOW)
    for sp in store.posts():
        for photo in sp.post.all_photos:
            path = media / "photos" / f"{photo.uid}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"jpeg")
            store.record_photo(photo, f"photos/{photo.uid}.jpg", 10, 10, NOW)
    return store, media


def photo(photo_id: int) -> Photo:
    return Photo(owner_id=-GROUP, id=photo_id, url="https://pp.example/x.jpg", width=1, height=1)


def file_of(media: Path, photo_id: int) -> Path:
    return media / "photos" / f"{photo(photo_id).uid}.jpg"


def delete_post(store: Store, post_id: int, last_used: int) -> None:
    """Пост снят в VK; его фото последний раз отмечены экспортом в last_used."""
    store.mark_deleted([(-GROUP, post_id)], last_used)
    ids = [p.id for sp in store.posts(include_deleted=True) if sp.post.id == post_id for p in sp.post.all_photos]
    store.touch_photos([photo(i) for i in ids], last_used)


def test_used_photos_untouched(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    result = cleanup_media(store, media, NOW + 60 * DAY)  # живые посты, хоть отметке и 60 дней
    assert result.removed == [] and result.in_use == 3
    assert all(file_of(media, i).is_file() for i in (1, 2, 3))


def test_29_days_stays_31_days_removed(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    delete_post(store, 102, NOW - 29 * DAY)
    assert cleanup_media(store, media, NOW).removed == []
    assert file_of(media, 3).is_file()
    delete_post(store, 102, NOW - 31 * DAY)
    result = cleanup_media(store, media, NOW)
    assert result.removed == [f"photos/{photo(3).uid}.jpg"]
    assert not file_of(media, 3).exists() and store.photo_info(photo(3)) is None
    assert file_of(media, 1).is_file() and file_of(media, 2).is_file()  # чужие фото на месте


def test_restored_post_brings_photo_back_to_used(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    delete_post(store, 102, NOW - 25 * DAY)
    store.upsert(post_obj(102, attachments=[photo_att(3)]), NOW)  # пост снова в VK
    result = cleanup_media(store, media, NOW + 10 * DAY)  # 35 дней от последней отметки
    assert result.removed == [] and file_of(media, 3).is_file()


def test_photo_shared_with_live_post_stays(tmp_path: Path) -> None:
    """Одно фото у удаленного и у живого поста (репост, повтор) - не удаляется."""
    store, media = setup(tmp_path)
    store.upsert(post_obj(103, attachments=[photo_att(3)]), NOW)
    delete_post(store, 102, NOW - 40 * DAY)
    assert cleanup_media(store, media, NOW).removed == [] and file_of(media, 3).is_file()


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    delete_post(store, 102, NOW - 40 * DAY)
    result = cleanup_media(store, media, NOW, dry_run=True)
    assert result.removed == [f"photos/{photo(3).uid}.jpg"]
    assert file_of(media, 3).is_file() and store.photo_info(photo(3)) is not None


def test_missing_file_only_forgets_record(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    delete_post(store, 102, NOW - 40 * DAY)
    file_of(media, 3).unlink()
    assert len(cleanup_media(store, media, NOW).removed) == 1
    assert store.photo_info(photo(3)) is None


def test_foreign_names_and_symlinks_refused(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    delete_post(store, 101, NOW - 40 * DAY)
    outside = tmp_path / "важное.jpg"
    outside.write_bytes(b"x")
    # Фото 1 записано под чужим именем, фото 2 - ссылка наружу.
    store.record_photo(photo(1), "../важное.jpg", 10, 10, NOW)
    store.touch_photos([photo(1)], NOW - 40 * DAY)
    file_of(media, 2).unlink()
    os.symlink(outside, file_of(media, 2))
    result = cleanup_media(store, media, NOW)
    assert result.removed == [] and len(result.refused) == 2
    assert outside.read_bytes() == b"x" and file_of(media, 2).is_symlink()
    assert store.photo_info(photo(1)) is not None  # запись не тронута


def test_removed_photo_downloads_again_when_needed(tmp_path: Path) -> None:
    """После чистки записи нет - скачивание видит фото как новое (если пост вернется позже)."""
    store, media = setup(tmp_path)
    delete_post(store, 102, NOW - 40 * DAY)
    cleanup_media(store, media, NOW)
    store.upsert(post_obj(102, attachments=[photo_att(3)]), NOW)
    missing = [p for sp in store.posts() for p in sp.post.all_photos if store.photo_info(p) is None]
    assert [p.id for p in missing] == [3]


def worker_settings(tmp_path: Path) -> Settings:
    return load_settings(
        {
            "DOBROMIR_DATA": str(tmp_path / "data"),
            "SITE_ROOT": str(tmp_path / "site"),
            "SITE_ENV": "staging",
            "VK_SERVICE_TOKEN": "vk1.a.MEDIA-SECRET",
            "VK_GROUP_ID": str(GROUP),
        }
    )


def old_deleted_photo(tmp_path: Path) -> Path:
    """В базе удаленный давно пост 900 с фото 9, отмеченным 40 дней назад."""
    s = worker_settings(tmp_path)
    store = Store(open_db(s.data.db))
    store.upsert(post_obj(900, date=1785000000, attachments=[photo_att(9)]), NOW - 50 * DAY)
    store.mark_deleted([(-GROUP, 900)], NOW - 40 * DAY)
    path = s.site.media / "photos" / f"{photo(9).uid}.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"jpeg")
    store.record_photo(photo(9), f"photos/{photo(9).uid}.jpg", 10, 10, NOW - 40 * DAY)
    store.close()
    return path


def test_worker_cleans_daily_on_fresh_site(tmp_path: Path) -> None:
    path = old_deleted_photo(tmp_path)
    code = run_worker(
        worker_settings(tmp_path), FakeWall(3).http(), now=NOW, build=lambda s, n: None, stderr=io.StringIO()
    )
    assert code == EXIT_OK and not path.exists()


def test_worker_keeps_media_while_site_outdated(tmp_path: Path) -> None:
    """Сборка не прошла - текущий релиз может еще показывать удаленный пост с этим фото."""
    path = old_deleted_photo(tmp_path)
    code = run_worker(worker_settings(tmp_path), FakeWall(3).http(), now=NOW, build=None, stderr=io.StringIO())
    assert code == EXIT_OK and path.is_file()
