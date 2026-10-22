"""Наша модель поста. Поля, которых нет в ней, из VK не берем."""

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

# Крым живет по московскому времени; фиксированное смещение, без базы часовых поясов.
LOCAL_TZ = timezone(timedelta(hours=3))


class Photo(BaseModel):
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


class Post(BaseModel):
    owner_id: int
    id: int
    timestamp: int
    title: str
    text: str
    tags: list[str]
    pinned: bool
    photos: list[Photo]
    links: list[Link]
    skipped: list[str]  # типы вложений, которые мы не берем (видео и прочее)

    @property
    def date(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, timezone.utc).astimezone(LOCAL_TZ)

    @property
    def slug(self) -> str:
        """Имя папки: дата поста и его id в VK, по нему видно, что пост уже импортирован."""
        return f"{self.date:%Y-%m-%d}-vk{self.id}"

    @property
    def vk_url(self) -> str:
        return f"https://vk.com/wall{self.owner_id}_{self.id}"
