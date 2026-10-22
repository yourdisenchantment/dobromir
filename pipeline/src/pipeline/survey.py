"""Разведка стены: какие поля отдает VK и сколько постов видит каждый ключ.

Только чтение (`wall.get`). Сырые ответы - в `<DOBROMIR_DATA>/survey/<время>/`,
вне репозитория. В отчет не попадают ни ключи, ни тексты постов - только
структура, количества и id.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.vk.client import VkClient, VkError


@dataclass
class KeyResult:
    key: str
    reported_count: int | None = None
    posts: list[dict[str, Any]] = field(default_factory=list)
    pages: int = 0
    error: str | None = None
    stopped: str = ""


def walk_wall(vk: VkClient, out_dir: Path, page_size: int, max_pages: int) -> KeyResult:
    """Листает стену страницами, пока VK отдает посты. Каждый сырой ответ - в отдельный файл."""
    result = KeyResult(key=out_dir.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    offset = 0
    while result.pages < max_pages:
        try:
            resp = vk.wall_get(offset=offset, count=page_size, extended=True)
        except VkError as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            result.stopped = f"ошибка на offset={offset}"
            return result
        result.pages += 1
        (out_dir / f"page-{result.pages:03d}.json").write_text(
            json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result.reported_count = resp.get("count")
        items = resp["items"]
        result.posts.extend(items)
        offset += len(items)
        if not items:
            result.stopped = f"пустая страница на offset={offset}"
            break
        if result.reported_count is not None and offset >= result.reported_count:
            result.stopped = "дошли до count"
            break
    else:
        result.stopped = f"остановлено лимитом страниц ({max_pages})"
    return result


def _keys(objs: list[dict[str, Any]]) -> Counter[str]:
    c: Counter[str] = Counter()
    for o in objs:
        c.update(o.keys())
    return c


def _table(counter: Counter[str], total: int) -> list[str]:
    return [f"| `{k}` | {n}/{total} |" for k, n in sorted(counter.items())]


def describe(res: KeyResult) -> list[str]:
    """Отчет по одному ключу: охват и инвентарь полей."""
    lines = [f"## Ключ: {res.key}", ""]
    if res.error:
        lines += [f"**Ошибка:** {res.error}", ""]
    posts = res.posts
    ids = [p.get("id") for p in posts]
    unique = sorted({i for i in ids if isinstance(i, int)})
    lines += [
        f"- `count` в ответе VK: {res.reported_count}",
        f"- получено постов: {len(posts)}, уникальных id: {len(unique)}, страниц: {res.pages}",
        f"- почему остановились: {res.stopped}",
    ]
    if not posts:
        return [*lines, ""]
    dates = [p["date"] for p in posts if isinstance(p.get("date"), int)]
    if dates:
        fmt = "%Y-%m-%d"
        oldest = datetime.fromtimestamp(min(dates), timezone.utc).strftime(fmt)
        newest = datetime.fromtimestamp(max(dates), timezone.utc).strftime(fmt)
        lines.append(f"- даты постов: {oldest} - {newest} (UTC)")
    lines.append(f"- id: {unique[0]} - {unique[-1]}; повторов id: {len(ids) - len(set(ids))}")
    pinned = [p.get("id") for p in posts if p.get("is_pinned")]
    lines.append(
        f"- закрепленные (`is_pinned`): {pinned or 'нет'}; позиции в выдаче: "
        f"{[i for i, p in enumerate(posts) if p.get('is_pinned')] or '-'}"
    )
    lines.append(f"- с полем `edited`: {sum(1 for p in posts if 'edited' in p)}")
    lines.append(f"- репостов (`copy_history`): {sum(1 for p in posts if p.get('copy_history'))}")
    owner = posts[0].get("owner_id")
    lines.append(f"- не от имени группы (`from_id != owner_id`): {sum(1 for p in posts if p.get('from_id') != owner)}")
    lines.append(f"- `post_type`: {dict(Counter(str(p.get('post_type')) for p in posts))}")
    lines += ["", "### Поля поста", "", "| поле | в скольких постах |", "|---|---|", *_table(_keys(posts), len(posts))]

    atts = [a for p in posts for a in (p.get("attachments") or [])]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for a in atts:
        t = str(a.get("type"))
        by_type.setdefault(t, []).append(a.get(t) or {})
    lines += ["", "### Вложения", "", f"Всего: {len(atts)}; по типам: {dict(Counter(a.get('type') for a in atts))}"]
    for t, objs in sorted(by_type.items()):
        lines += ["", f"#### `{t}`", "", "| поле | сколько |", "|---|---|", *_table(_keys(objs), len(objs))]
        if t == "photo":
            sizes = [s for o in objs for s in (o.get("sizes") or [])]
            widths = [s.get("width", 0) for s in sizes]
            zero = sum(1 for w in widths if not w)
            types = dict(Counter(str(s.get("type")) for s in sizes))
            lines += [
                "",
                f"- размеры (`sizes[].type`): {types}",
                f"- максимальная ширина: {max(widths) if widths else '-'}; размеров с width=0: {zero}",
                f"- с `orig_photo`: {sum(1 for o in objs if o.get('orig_photo'))}",
            ]
    reposts = [r for p in posts for r in (p.get("copy_history") or [])]
    if reposts:
        lines += [
            "",
            "### Оригиналы репостов (`copy_history[]`)",
            "",
            "| поле | сколько |",
            "|---|---|",
            *_table(_keys(reposts), len(reposts)),
        ]
    return [*lines, ""]


def compare(results: list[KeyResult]) -> list[str]:
    if len(results) < 2:
        return []
    sets = {r.key: {p["id"] for p in r.posts if isinstance(p.get("id"), int)} for r in results}
    a, b = results[0].key, results[1].key
    return [
        "## Сравнение ключей",
        "",
        f"- `count`: {a} = {results[0].reported_count}, {b} = {results[1].reported_count}",
        f"- id только у {a}: {sorted(sets[a] - sets[b]) or 'нет'}",
        f"- id только у {b}: {sorted(sets[b] - sets[a]) or 'нет'}",
        "",
    ]


def run_survey(clients: dict[str, VkClient], out_root: Path, page_size: int, max_pages: int) -> Path:
    """Обходит стену каждым ключом и пишет `report.md`. Возвращает путь к отчету."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = out_root / stamp
    results = [walk_wall(vk, out / key, page_size, max_pages) for key, vk in clients.items()]
    lines = [f"# Разведка стены VK, {stamp} UTC", "", f"Сырые ответы: `{out}`", ""]
    for r in results:
        lines += describe(r)
    lines += compare(results)
    report = out / "report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report
