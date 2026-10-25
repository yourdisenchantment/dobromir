"""Чистка медиа: фото без ссылок из базы удаляются, остальные - нет; белый список, пробный режим, воркер."""

import io
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fakevk import FakeWall
from pipeline.media.cleanup import cleanup_media
from pipeline.media.photos import PhotoFiles, Rendition
from pipeline.parse import Photo
from pipeline.settings import Settings, load_settings
from pipeline.store import Store, open_db
from pipeline.worker import EXIT_OK, run_worker
from samples import GROUP, photo_att, post_obj

TZ = ZoneInfo("Europe/Simferopol")
DAY = 86400
NOW = int(datetime(2026, 10, 24, 4, 0, tzinfo=TZ).timestamp())
OLD = NOW - 40 * DAY  # дата публикации поста 102
NEW = NOW - 2 * DAY  # дата публикации поста 101


def setup(tmp_path: Path) -> tuple[Store, Path]:
    """Пост 101 (свежий) с фото 1 и 2, пост 102 (старый) с фото 3; у каждого фото две копии."""
    store = Store(open_db(tmp_path / "db.sqlite"))
    media = tmp_path / "media"
    store.upsert(post_obj(101, date=NEW, attachments=[photo_att(1), photo_att(2)]), NOW)
    store.upsert(post_obj(102, date=OLD, attachments=[photo_att(3)]), NOW)
    for sp in store.posts():
        for photo in sp.post.all_photos:
            files = two_files(photo)
            for name in files.files:
                (media / name).parent.mkdir(parents=True, exist_ok=True)
                (media / name).write_bytes(b"webp")
            store.record_photo(photo, files, NOW)
    return store, media


def two_files(photo: Photo) -> PhotoFiles:
    """Копия для окна и превью - как у фото крупнее 800 px."""
    return PhotoFiles(
        full=Rendition(f"photos/{photo.uid}.webp", 1600, 1200),
        preview=Rendition(f"photos/{photo.uid}-800.webp", 800, 600),
    )


def photo(photo_id: int) -> Photo:
    return Photo(owner_id=-GROUP, id=photo_id, url="https://pp.example/x.jpg", width=1, height=1)


def file_of(media: Path, photo_id: int) -> Path:
    return media / "photos" / f"{photo(photo_id).uid}.webp"


def preview_of(media: Path, photo_id: int) -> Path:
    return media / "photos" / f"{photo(photo_id).uid}-800.webp"


def test_referenced_photos_untouched(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    assert cleanup_media(store, media).removed == []
    assert all(file_of(media, i).is_file() and preview_of(media, i).is_file() for i in (1, 2, 3))


def test_expired_post_photos_removed_both_copies(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    assert store.expire_posts(NOW - 30 * DAY) == 1  # пост 102 старше срока
    result = cleanup_media(store, media)
    assert result.removed == [f"photos/{photo(3).uid}.webp", f"photos/{photo(3).uid}-800.webp"]
    assert not file_of(media, 3).exists() and not preview_of(media, 3).exists()
    assert store.photo_info(photo(3)) is None
    assert file_of(media, 1).is_file() and preview_of(media, 2).is_file()  # фото свежего поста на месте


def test_soft_deleted_post_keeps_photos_until_expiry(tmp_path: Path) -> None:
    """Пост удалили в VK: он в базе помечен, фото остаются - вернут пост, вернется и фото."""
    store, media = setup(tmp_path)
    store.mark_deleted([(-GROUP, 101)], NOW)
    assert cleanup_media(store, media).removed == []
    assert file_of(media, 1).is_file()


def test_photo_shared_with_remaining_post_stays(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    store.upsert(post_obj(103, date=NEW, attachments=[photo_att(3)]), NOW)  # то же фото в свежем посте
    store.expire_posts(NOW - 30 * DAY)
    assert cleanup_media(store, media).removed == [] and file_of(media, 3).is_file()


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    store.expire_posts(NOW - 30 * DAY)
    result = cleanup_media(store, media, dry_run=True)
    assert len(result.removed) == 2
    assert file_of(media, 3).is_file() and preview_of(media, 3).is_file()
    assert store.photo_info(photo(3)) is not None


def test_missing_file_only_forgets_record(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    store.expire_posts(NOW - 30 * DAY)
    file_of(media, 3).unlink()
    assert len(cleanup_media(store, media).removed) == 2
    assert not preview_of(media, 3).exists() and store.photo_info(photo(3)) is None


def test_foreign_names_and_symlinks_refused(tmp_path: Path) -> None:
    store, media = setup(tmp_path)
    store.expire_posts(NOW + DAY)  # все посты ушли по сроку
    outside = tmp_path / "важное.jpg"
    outside.write_bytes(b"x")
    # Фото 1 записано под чужим именем, фото 2 - ссылка наружу.
    alien = Rendition("../важное.jpg", 10, 10)
    store.record_photo(photo(1), PhotoFiles(alien, alien), NOW)
    file_of(media, 2).unlink()
    os.symlink(outside, file_of(media, 2))
    result = cleanup_media(store, media)
    assert len(result.refused) == 2 and result.removed == two_files(photo(3)).files
    assert outside.read_bytes() == b"x" and file_of(media, 2).is_symlink()
    assert store.photo_info(photo(1)) is not None  # запись не тронута
    assert preview_of(media, 2).is_file()  # у фото со ссылкой не тронута и вторая копия


def test_removed_photo_downloads_again_when_needed(tmp_path: Path) -> None:
    """После чистки записи нет - скачивание видит фото как новое, если оно снова понадобится."""
    store, media = setup(tmp_path)
    store.expire_posts(NOW - 30 * DAY)
    cleanup_media(store, media)
    store.upsert(post_obj(104, date=NEW, attachments=[photo_att(3)]), NOW)
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


def orphan_photo(tmp_path: Path) -> Path:
    """В базе запись о фото 9, на которое не ссылается ни один пост (его пост ушел по сроку)."""
    s = worker_settings(tmp_path)
    store = Store(open_db(s.data.db))
    path = s.site.media / "photos" / f"{photo(9).uid}.webp"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"webp")
    small = Rendition(f"photos/{photo(9).uid}.webp", 640, 480)  # маленькое фото: один файл
    store.record_photo(photo(9), PhotoFiles(small, small), NOW - 40 * DAY)
    store.close()
    return path


def test_worker_cleans_on_fresh_site(tmp_path: Path) -> None:
    path = orphan_photo(tmp_path)
    code = run_worker(
        worker_settings(tmp_path), FakeWall(3).http(), now=NOW, build=lambda s, n: None, stderr=io.StringIO()
    )
    assert code == EXIT_OK and not path.exists()


def test_worker_keeps_media_while_site_outdated(tmp_path: Path) -> None:
    """Сборка не прошла - текущий релиз может еще показывать пост с этим фото."""
    path = orphan_photo(tmp_path)
    code = run_worker(worker_settings(tmp_path), FakeWall(3).http(), now=NOW, build=None, stderr=io.StringIO())
    assert code == EXIT_OK and path.is_file()
