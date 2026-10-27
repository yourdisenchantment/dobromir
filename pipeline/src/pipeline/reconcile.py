"""Сверка базы со стеной VK: окно последних постов и суточная полная сверка.

Сеть передается снаружи (`VkClient`), здесь только решения. Главное правило:
пост считается удаленным, только если VK явно ответил, но без него. Ошибка сети,
ключа, VK или пустой ответ целиком - это «не знаем», а не «удален».
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pipeline.store.state import Change, Store
from pipeline.sync import ingest
from pipeline.vk.client import VkClient

LAST_FULL_RECONCILE = "last_full_reconcile_date"
# Перекрытие страниц при листании: если пока листаем, на стене появился пост, все
# сдвигается на одну позицию - нахлест не дает пропустить пост на стыке страниц.
PAGE_OVERLAP = 5


class SyncError(RuntimeError):
    """Сверка остановлена ради сохранности данных: база не изменена."""


@dataclass
class ReconcileResult:
    changes: Counter[Change] = field(default_factory=Counter)
    deleted: int = 0
    checked: int = 0  # сколько постов сверено по одному (getById)


def merge_responses(responses: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Склеивает страницы в один ответ: посты без повторов (первая встреча побеждает), все имена."""
    items: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    groups: dict[int, dict[str, Any]] = {}
    profiles: dict[int, dict[str, Any]] = {}
    for resp in responses:
        for obj in resp.get("items") or []:
            key = (obj.get("owner_id"), obj.get("id"))
            if key not in seen:
                seen.add(key)
                items.append(obj)
        for g in resp.get("groups") or []:
            groups[g["id"]] = g
        for p in resp.get("profiles") or []:
            profiles[p["id"]] = p
    return {"items": items, "groups": list(groups.values()), "profiles": list(profiles.values())}


def fetch_wall(vk: VkClient, limit: int | None, page_size: int, since: int | None = None) -> dict[str, Any]:
    """Посты со стены, новые первыми. limit - сколько обычных постов (закреп не в счет); None - вся стена.
    since - не листать дальше страницы, где встретился обычный пост старше (первичная загрузка за
    срок хранения): обычные посты идут по убыванию даты, дальше только старее.

    Закрепленный пост VK отдает первым при offset=0, поэтому он не занимает место в окне
    и учитывается один раз.
    """
    pages: list[dict[str, Any]] = []
    offset = 0
    regular: set[int] = set()
    total: int | None = None
    complete = False
    while True:
        resp = vk.wall_get(offset=offset, count=page_size, extended=True)
        pages.append(resp)
        total = resp.get("count", total)
        items = resp["items"]
        regular.update(p["id"] for p in items if not p.get("is_pinned"))
        if not items:
            break
        if limit is not None and len(regular) >= limit:
            complete = True
            break
        if since is not None and any(int(p.get("date") or 0) < since for p in items if not p.get("is_pinned")):
            break
        if total is not None and offset + len(items) >= total:
            complete = True
            break
        offset += max(1, len(items) - PAGE_OVERLAP)
    merged = merge_responses(pages)
    if limit is not None:
        merged["items"] = _first_regular(merged["items"], limit)
    # Окно получено целиком: набрали limit обычных постов или дошли до конца стены.
    # Только по целому окну можно судить, что пропавший из него пост удален.
    merged["complete"] = complete
    return merged


def _first_regular(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Закреп(ы) плюс первые limit обычных постов."""
    out: list[dict[str, Any]] = []
    count = 0
    for obj in items:
        if obj.get("is_pinned"):
            out.append(obj)
        elif count < limit:
            out.append(obj)
            count += 1
    return out


def reconcile_window(
    store: Store, vk: VkClient, window: int, page_size: int, now: int, since: int | None = None
) -> ReconcileResult:
    """Новые, измененные, вернувшиеся и удаленные посты в пределах последних `window`.

    Удален - сохраненный пост, чья дата не старше самого старого обычного поста окна, но
    которого в окне нет (отчет о хостинге, разд. 9 п. 13): так снятый пост исчезает за час,
    а не ждет суточной сверки. Пост старше окна - просто старый, его проверяет суточная.
    """
    response = fetch_wall(vk, window, page_size)
    missing = window_missing(store, response)
    _guard(missing, len(store.live_keys()), "окно")
    result = ReconcileResult()
    result.changes = ingest(store, [response], now, since)
    result.deleted = store.mark_deleted(sorted(missing), now)
    return result


def window_missing(store: Store, response: dict[str, Any]) -> set[tuple[int, int]]:
    """Какие сохраненные посты пропали из окна. Пустое или неполное окно - «не знаем».

    Границу окна задают только обычные посты: закреп VK отдает первым, даже если он
    старый, и по его дате «окно» растянулось бы на всю стену.
    """
    items = response.get("items") or []
    regular = [p for p in items if not p.get("is_pinned") and isinstance(p.get("date"), int)]
    if not response.get("complete") or not regular:
        return set()
    oldest = min(p["date"] for p in regular)
    present = {(p.get("owner_id"), p.get("id")) for p in items if not _marked_deleted(p)}
    return {key for key in store.live_keys_since(oldest) if key not in present}


def _guard(missing: set[Any], live: int, where: str) -> None:
    """Больше max(3, 20% живых) удалений за раз - скорее сбой VK, ничего не применяем."""
    limit = max(3, live * 20 // 100)
    if len(missing) > limit:
        raise SyncError(
            f"{where}: сверка хочет удалить {len(missing)} из {live} постов (порог {limit}): "
            "похоже на сбой VK, ничего не изменено"
        )


def classify_missing(batches: list[tuple[list[int], dict[str, Any]]]) -> set[int]:
    """Какие посты считать удаленными по ответам всех пачек одной сверки.

    Единственное место, где решается «удален или не знаем». Если пусто ответили **все**
    пачки - это «не знаем» (VK, похоже, отдает пусто на все). Иначе удален тот, кого нет
    в ответе своей пачки, - даже если пачка пришла пустой целиком: иначе посты, оказавшиеся
    в одной пачке (например, самые старые), никогда не удалились бы. Случайный сбой одной
    пачки ловит защита от массового удаления в `full_reconcile`.
    """
    if not any(response.get("items") for _, response in batches):
        return set()
    missing: set[int] = set()
    for requested, response in batches:
        present = {obj.get("id") for obj in response.get("items") or [] if not _marked_deleted(obj)}
        missing |= {post_id for post_id in requested if post_id not in present}
    return missing


def _marked_deleted(obj: dict[str, Any]) -> bool:
    # Допущение: так VK может помечать удаленный пост вместо того, чтобы не отдать его (проверить в P1-1).
    return bool(obj.get("is_deleted") or obj.get("deleted_reason"))


def full_reconcile(store: Store, vk: VkClient, batch: int, now: int, since: int | None = None) -> ReconcileResult:
    """Все живые посты базы через `wall.getById` пачками.

    Сначала все ответы, потом решения: при любой ошибке VK исключение уходит наружу до
    того, как что-то записано. Если к удалению больше max(3, 20% живых) - ничего не
    применяется и поднимается SyncError: скорее сбой VK, чем массовое удаление.
    """
    keys = store.live_keys()
    if not keys:
        return ReconcileResult()
    owner = keys[0][0]
    ids = [post_id for _, post_id in keys]
    batches: list[tuple[list[int], dict[str, Any]]] = []
    for start in range(0, len(ids), batch):
        chunk = ids[start : start + batch]
        batches.append((chunk, vk.wall_get_by_id(chunk, extended=True)))  # VkError - наружу, база не тронута
    missing = classify_missing(batches)
    responses = [resp for _, resp in batches]

    _guard(missing, len(ids), "суточная сверка")
    result = ReconcileResult(checked=len(ids))
    result.changes = ingest(store, responses, now, since)
    result.deleted = store.mark_deleted([(owner, i) for i in sorted(missing)], now)
    return result


def local_date(now: int, tz: ZoneInfo) -> str:
    return datetime.fromtimestamp(now, tz).date().isoformat()


def full_reconcile_due(store: Store, now: int, tz: ZoneInfo, after_hour: int) -> bool:
    """Первый запуск после after_hour по местному времени, если сегодня сверки еще не было."""
    local = datetime.fromtimestamp(now, tz)
    return local.hour >= after_hour and store.get_meta(LAST_FULL_RECONCILE) != local.date().isoformat()


def mark_full_reconciled(store: Store, now: int, tz: ZoneInfo) -> None:
    store.set_meta(LAST_FULL_RECONCILE, local_date(now, tz))
