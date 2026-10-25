"""Наша модель поста. Поля, которых нет в ней, из VK не берем."""

from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from pipeline.settings import DEFAULT_TZ_NAME

# Часовой пояс, в котором показываются даты и строится slug. Через базу зон, а не
# фиксированным смещением: пост в 23:30 по Симферополю не должен уехать на другой день.
LOCAL_TZ = ZoneInfo(DEFAULT_TZ_NAME)
# Длинная сторона копии фото для показа (решено 2026-10-25). Здесь, а не в media: по ней
# разбор выбирает, какой размер скачивать.
DISPLAY_MAX = 1600


class Photo(BaseModel):
    """Фото для скачивания. `url` временный (подписан VK) и в экспорт не идет."""

    owner_id: int
    id: int
    url: str
    width: int
    height: int

    @property
    def uid(self) -> str:
        return f"{self.owner_id}_{self.id}".replace("-", "m")


class Link(BaseModel):
    url: str
    title: str


class VkMedia(BaseModel):
    """Документ или видео: файл не храним, на сайте - ссылка на VK (решено 2026-10-23)."""

    kind: Literal["doc", "video"]
    owner_id: int
    id: int
    title: str


class Content(BaseModel):
    """То, что показывается на сайте: общее у поста и оригинала репоста."""

    owner_id: int
    id: int
    timestamp: int
    text: str
    photos: list[Photo]
    links: list[Link]
    media: list[VkMedia]
    skipped: list[str]  # типы вложений, которые не показываем (опросы и прочее)

    @property
    def vk_url(self) -> str:
        return f"https://vk.com/wall{self.owner_id}_{self.id}"


class Repost(Content):
    """Оригинал репоста. Имя источника - из `groups`/`profiles` ответа с extended=1."""

    source_name: str | None


class Post(Content):
    edited: int | None  # время правки из VK; нет поля - поста не правили
    title: str
    tags: list[str]
    pinned: bool
    repost: Repost | None

    @property
    def date(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, timezone.utc).astimezone(LOCAL_TZ)

    @property
    def all_photos(self) -> list[Photo]:
        """Фото поста и оригинала репоста: их скачивают и их же бережет чистка медиа."""
        return list(self.photos) + (list(self.repost.photos) if self.repost else [])

    @property
    def slug(self) -> str:
        """Дата поста по местному времени и его id в VK: уникально и не меняется при правке."""
        return f"{self.date:%Y-%m-%d}-vk{self.id}"
