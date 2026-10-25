"""Работа с базой воркера: посты, скачанные фото, отметки."""

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pipeline.media.photos import PhotoFiles, Rendition
from pipeline.parse import Photo, Post, content_hash, parse_post


class Change(str, Enum):
    """Что произошло с постом при записи. Все, кроме SAME, - повод пересобрать сайт."""

    NEW = "new"
    CHANGED = "changed"
    RESTORED = "restored"
    SAME = "same"


@dataclass(frozen=True)
class PhotoRecord:
    """Запись о скачанном фото. preview None - запись старого вида (исходный JPEG до
    2026-10-25): скачивание фото пересчитает ее из этого файла."""

    file: str
    width: int
    height: int
    preview: Rendition | None

    @property
    def files(self) -> list[str]:
        names = [self.file] + ([self.preview.file] if self.preview else [])
        return list(dict.fromkeys(names))


@dataclass(frozen=True)
class StoredPost:
    post: Post
    raw: dict[str, Any]
    deleted_at: int | None


class Store:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._db = conn

    def close(self) -> None:
        self._db.close()

    # --- посты ---

    def upsert(self, obj: dict[str, Any], now: int, source_name: str | None = None) -> Change:
        """Записывает пост из ответа VK.

        Изменением считается смена показываемого: хэш содержимого или закреп (закреп в хэш
        не входит, но меняет вид ленты). Счетчики и подписи адресов фото - не изменение,
        хотя raw_json обновляется всегда, чтобы в базе лежал последний ответ VK.
        """
        post = with_source(parse_post(obj), source_name)
        digest = content_hash(post)
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        row = self._db.execute(
            "SELECT content_hash, pinned, deleted_at FROM posts WHERE owner_id = ? AND id = ?",
            (post.owner_id, post.id),
        ).fetchone()
        with self._db:
            if row is None:
                self._db.execute(
                    "INSERT INTO posts (owner_id, id, date, edited_at, content_hash, pinned, repost_source,"
                    " raw_json, first_seen_at, last_seen_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        post.owner_id,
                        post.id,
                        post.timestamp,
                        post.edited,
                        digest,
                        int(post.pinned),
                        source_name,
                        raw,
                        now,
                        now,
                        now,
                    ),
                )
                return Change.NEW
            restored = row["deleted_at"] is not None
            changed = row["content_hash"] != digest or bool(row["pinned"]) != post.pinned
            self._db.execute(
                "UPDATE posts SET date = ?, edited_at = ?, content_hash = ?, pinned = ?,"
                " repost_source = COALESCE(?, repost_source), raw_json = ?, last_seen_at = ?,"
                " updated_at = CASE WHEN ? THEN ? ELSE updated_at END, deleted_at = NULL"
                " WHERE owner_id = ? AND id = ?",
                (
                    post.timestamp,
                    post.edited,
                    digest,
                    int(post.pinned),
                    source_name,
                    raw,
                    now,
                    int(changed or restored),
                    now,
                    post.owner_id,
                    post.id,
                ),
            )
        if restored:
            return Change.RESTORED
        return Change.CHANGED if changed else Change.SAME

    def mark_deleted(self, keys: Iterable[tuple[int, int]], now: int) -> int:
        """Мягкое удаление. Решение «пост удален» принимает сверка (P1-4), здесь только запись."""
        count = 0
        with self._db:
            for owner_id, post_id in keys:
                cur = self._db.execute(
                    "UPDATE posts SET deleted_at = ?, updated_at = ? WHERE owner_id = ? AND id = ?"
                    " AND deleted_at IS NULL",
                    (now, now, owner_id, post_id),
                )
                count += cur.rowcount
        return count

    def expire_posts(self, published_before: int) -> int:
        """Физически удаляет посты, опубликованные раньше срока хранения (решено 2026-10-26).
        Их фото уберет чистка медиа: на них больше не ссылается ни один пост."""
        with self._db:
            return self._db.execute("DELETE FROM posts WHERE date < ?", (published_before,)).rowcount

    def posts(self, include_deleted: bool = False) -> list[StoredPost]:
        """Посты из базы, разобранные заново из raw_json; новые первыми."""
        sql = "SELECT raw_json, repost_source, deleted_at FROM posts"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        sql += " ORDER BY date DESC, id DESC"
        result: list[StoredPost] = []
        for row in self._db.execute(sql):
            raw = json.loads(row["raw_json"])
            post = with_source(parse_post(raw), row["repost_source"])
            result.append(StoredPost(post=post, raw=raw, deleted_at=row["deleted_at"]))
        return result

    def counts(self) -> tuple[int, int]:
        """Сколько постов живых и сколько помечено удаленными."""
        row = self._db.execute("SELECT COUNT(*) - COUNT(deleted_at), COUNT(deleted_at) FROM posts").fetchone()
        return int(row[0]), int(row[1])

    def live_keys_since(self, date: int) -> list[tuple[int, int]]:
        """Живые посты с датой публикации не раньше date."""
        return [
            (r["owner_id"], r["id"])
            for r in self._db.execute("SELECT owner_id, id FROM posts WHERE deleted_at IS NULL AND date >= ?", (date,))
        ]

    def live_keys(self) -> list[tuple[int, int]]:
        return [
            (r["owner_id"], r["id"])
            for r in self._db.execute(
                "SELECT owner_id, id FROM posts WHERE deleted_at IS NULL ORDER BY date DESC, id DESC"
            )
        ]

    # --- фото ---

    def record_photo(self, photo: Photo, files: PhotoFiles, now: int) -> None:
        full, preview = files.full, files.preview
        with self._db:
            self._db.execute(
                "INSERT INTO photos (owner_id, id, file_name, width, height, preview_file, preview_width,"
                " preview_height, downloaded_at, last_used_at) VALUES (?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT (owner_id, id) DO UPDATE SET file_name = excluded.file_name,"
                " width = excluded.width, height = excluded.height, preview_file = excluded.preview_file,"
                " preview_width = excluded.preview_width, preview_height = excluded.preview_height,"
                " downloaded_at = excluded.downloaded_at",
                (
                    photo.owner_id,
                    photo.id,
                    full.file,
                    full.width,
                    full.height,
                    preview.file,
                    preview.width,
                    preview.height,
                    now,
                    now,
                ),
            )

    def photo_info(self, photo: Photo) -> PhotoRecord | None:
        row = self._db.execute(
            "SELECT file_name, width, height, preview_file, preview_width, preview_height FROM photos"
            " WHERE owner_id = ? AND id = ?",
            (photo.owner_id, photo.id),
        ).fetchone()
        return None if row is None else _photo_record(row)

    def touch_photos(self, photos: Iterable[Photo], now: int) -> None:
        """Отмечает фото как используемые живыми постами (от этого считается срок чистки)."""
        with self._db:
            self._db.executemany(
                "UPDATE photos SET last_used_at = ? WHERE owner_id = ? AND id = ?",
                [(now, p.owner_id, p.id) for p in photos],
            )

    def photo_records(self) -> list[tuple[int, int, PhotoRecord]]:
        """Все записи о фото: (owner_id, id, запись)."""
        return [
            (int(r["owner_id"]), int(r["id"]), _photo_record(r))
            for r in self._db.execute(
                "SELECT owner_id, id, file_name, width, height, preview_file, preview_width, preview_height"
                " FROM photos ORDER BY owner_id, id"
            )
        ]

    def forget_photo(self, owner_id: int, photo_id: int) -> None:
        """Убирает запись о файле. Понадобится снова - фото скачается заново."""
        with self._db:
            self._db.execute("DELETE FROM photos WHERE owner_id = ? AND id = ?", (owner_id, photo_id))

    # --- отметки ---

    def get_meta(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def delete_meta(self, key: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM meta WHERE key = ?", (key,))

    def set_meta(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def _photo_record(row: sqlite3.Row) -> PhotoRecord:
    preview = (
        None
        if row["preview_file"] is None
        else Rendition(str(row["preview_file"]), int(row["preview_width"]), int(row["preview_height"]))
    )
    return PhotoRecord(str(row["file_name"]), int(row["width"]), int(row["height"]), preview)


def with_source(post: Post, source_name: str | None) -> Post:
    """Имя источника репоста приходит не в самом посте, а рядом (extended=1) - подставляем."""
    if post.repost is None or source_name is None:
        return post
    return post.model_copy(update={"repost": post.repost.model_copy(update={"source_name": source_name})})
