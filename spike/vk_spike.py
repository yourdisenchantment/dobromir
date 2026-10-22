#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Разведочный скрипт по VK API для сайта «Добромир».

Одноразовый, не часть будущего pipeline/. Ничего не скачивает и никуда не
пишет, кроме spike/out/ — только смотрит, что отдаёт API, и считает
статистику, от которой зависит контент-контракт. Вопросы — в spike/README.md.

    export VK_TOKEN=...
    uv run spike/vk_spike.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

API = "https://api.vk.com/method/"
VERSION = "5.199"
SCREEN_NAME = "dobromir.crimea"

OUT = Path(__file__).parent / "out"
HASHTAG = re.compile(r"#[^\s#]+")


class VkError(RuntimeError):
    pass


def call(client: httpx.Client, method: str, **params: Any) -> Any:
    """Один вызов API. VK отдаёт 200 даже на ошибку — она внутри тела."""
    resp = client.get(
        API + method,
        params={**params, "access_token": TOKEN, "v": VERSION},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        err = body["error"]
        raise VkError(f"{method}: [{err.get('error_code')}] {err.get('error_msg')}")
    return body["response"]


def dump(name: str, data: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def resolve_group(client: httpx.Client) -> tuple[int, dict[str, Any]]:
    """Экранное имя → числовой id. owner_id группы отрицательный."""
    resolved = call(client, "utils.resolveScreenName", screen_name=SCREEN_NAME)
    if not resolved or resolved.get("type") != "group":
        raise VkError(f"{SCREEN_NAME} не разрешилось в группу: {resolved!r}")
    group_id = resolved["object_id"]
    info = call(
        client,
        "groups.getById",
        group_id=group_id,
        fields="description,members_count,is_closed",
    )
    # В 5.199 ответ — объект с ключом "groups"; в старых версиях был список.
    group = (info["groups"] if isinstance(info, dict) else info)[0]
    dump("group", group)
    return -group_id, group


def probe_wall(client: httpx.Client, owner_id: int, limit: int = 100) -> dict[str, Any]:
    posts: list[dict[str, Any]] = []
    total = None
    while len(posts) < limit:
        batch = call(
            client, "wall.get", owner_id=owner_id, count=100, offset=len(posts)
        )
        total = batch["count"]
        items = batch["items"]
        if not items:
            break
        posts.extend(items)
    posts = posts[:limit]
    dump("wall", posts)

    # Эвристика заголовка: первая строка текста. Смотрим, осмысленна ли она.
    multiline = 0
    first_lines: list[int] = []
    empty_text = 0
    for post in posts:
        text = (post.get("text") or "").strip()
        if not text:
            empty_text += 1
            continue
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) > 1:
            multiline += 1
        first_lines.append(len(lines[0]))

    attachments = Counter()
    for post in posts:
        for att in post.get("attachments") or []:
            attachments[att.get("type", "?")] += 1

    tags = Counter()
    for post in posts:
        tags.update(HASHTAG.findall(post.get("text") or ""))

    pin_fields = sorted(
        {k for post in posts for k in post if "pin" in k.lower()}
    )
    reposts = sum(1 for post in posts if post.get("copy_history"))

    first_lines.sort()
    median = first_lines[len(first_lines) // 2] if first_lines else 0

    return {
        "всего постов в группе": total,
        "разобрано": len(posts),
        "без текста": empty_text,
        "многострочных (есть что взять как заголовок)": multiline,
        "медианная длина первой строки": median,
        "первых строк длиннее 100 символов": sum(1 for n in first_lines if n > 100),
        "вложения по типам": dict(attachments),
        "репостов (copy_history)": reposts,
        "поля про закреп": pin_fields,
        "уникальных хэштегов": len(tags),
        "топ хэштегов": dict(tags.most_common(10)),
    }


def probe_albums(client: httpx.Client, owner_id: int) -> dict[str, Any]:
    albums = call(client, "photos.getAlbums", owner_id=owner_id, need_covers=1)
    dump("albums", albums)
    items = albums.get("items", [])
    if not items:
        return {"альбомов": 0}

    biggest = max(items, key=lambda a: a.get("size", 0))
    photos = call(
        client,
        "photos.get",
        owner_id=owner_id,
        album_id=biggest["id"],
        count=200,
        photo_sizes=1,
        extended=1,
    )
    dump("photos_biggest_album", photos)

    # Какое максимальное разрешение VK вообще отдаёт — от этого зависит,
    # что такое «оригинал на скачивание» (план, раздел 8).
    widest = 0
    tallest = 0
    size_types = Counter()
    for photo in photos.get("items", []):
        for size in photo.get("sizes") or []:
            size_types[size.get("type", "?")] += 1
            widest = max(widest, size.get("width", 0))
            tallest = max(tallest, size.get("height", 0))

    untitled = sum(
        1 for a in items if not (a.get("title") or "").strip()
        or (a.get("title") or "").strip().lower().startswith("без названия")
    )

    return {
        "альбомов": len(items),
        "фото всего": sum(a.get("size", 0) for a in items),
        "самый большой альбом": f"{biggest.get('title')!r} — {biggest.get('size')} фото",
        "альбомов без осмысленного названия": untitled,
        "альбомов с описанием": sum(1 for a in items if (a.get("description") or "").strip()),
        "максимальное разрешение": f"{widest}x{tallest}",
        "типы размеров": dict(size_types),
    }


def render(title: str, data: dict[str, Any]) -> str:
    lines = [f"## {title}", ""]
    for key, value in data.items():
        lines.append(f"- **{key}:** {value}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    with httpx.Client() as client:
        owner_id, group = resolve_group(client)
        print(f"группа: {group.get('name')} (owner_id={owner_id})", file=sys.stderr)

        report = [
            "# Результат VK-спайка",
            "",
            f"Группа: **{group.get('name')}** (`{SCREEN_NAME}`, owner_id `{owner_id}`), "
            f"закрытая: `{group.get('is_closed')}`, участников: "
            f"{group.get('members_count')}.",
            "",
            "Сырые ответы — рядом, в `*.json`. Ниже только сводка; выводы по "
            "чек-листу из `../README.md` дописать руками.",
            "",
        ]

        for title, probe in (
            ("Посты (wall.get)", lambda: probe_wall(client, owner_id)),
            ("Альбомы (photos.getAlbums)", lambda: probe_albums(client, owner_id)),
        ):
            try:
                report.append(render(title, probe()))
            except VkError as exc:
                # Отказ по правам — это тоже результат спайка, а не сбой.
                report.append(f"## {title}\n\n**Недоступно:** {exc}\n")
                print(f"! {exc}", file=sys.stderr)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.md").write_text("\n".join(report), encoding="utf-8")
    print(f"готово: {OUT / 'summary.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    TOKEN = os.environ.get("VK_TOKEN", "")
    if not TOKEN:
        sys.exit("нужен VK_TOKEN в окружении (см. spike/README.md)")
    try:
        sys.exit(main())
    except (VkError, httpx.HTTPError) as exc:
        sys.exit(f"ошибка: {exc}")
