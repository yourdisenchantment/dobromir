-- Исходная схема. Время - секунды Unix (UTC). Миграции только добавляются, старые не правятся.

-- Посты стены. Источник правды - raw_json (последний ответ VK по посту): из него
-- всегда можно заново построить и разбор, и экспорт, не обращаясь к VK.
CREATE TABLE posts (
    owner_id      INTEGER NOT NULL,
    id            INTEGER NOT NULL,
    date          INTEGER NOT NULL,          -- публикация (поле date из VK)
    edited_at     INTEGER,                   -- поле edited из VK; NULL - не правили
    content_hash  TEXT    NOT NULL,          -- parse.hash.content_hash: только показываемое
    pinned        INTEGER NOT NULL DEFAULT 0,
    repost_source TEXT,                      -- имя источника репоста (из extended=1)
    raw_json      TEXT    NOT NULL,
    first_seen_at INTEGER NOT NULL,
    last_seen_at  INTEGER NOT NULL,          -- последний раз VK отдал пост
    updated_at    INTEGER NOT NULL,          -- последнее изменение показываемого
    deleted_at    INTEGER,                   -- мягкое удаление; NULL - пост живой
    PRIMARY KEY (owner_id, id)
);

CREATE INDEX posts_live_by_date ON posts (deleted_at, date DESC);

-- Скачанные фото. Ссылки VK временные, поэтому храним файл, а не адрес.
-- Какой пост какое фото использует, видно из raw_json; здесь - сам файл.
CREATE TABLE photos (
    owner_id      INTEGER NOT NULL,
    id            INTEGER NOT NULL,
    file_name     TEXT    NOT NULL,          -- путь относительно каталога media/
    width         INTEGER NOT NULL,
    height        INTEGER NOT NULL,
    downloaded_at INTEGER NOT NULL,
    last_used_at  INTEGER NOT NULL,          -- для чистки неиспользуемых (P2-2)
    PRIMARY KEY (owner_id, id)
);

-- Отметки воркера: сверки, сборки, флаг «сайт устарел».
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
