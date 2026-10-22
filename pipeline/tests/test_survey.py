import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx

from pipeline.settings import VkSettings
from pipeline.survey import run_survey, walk_wall
from pipeline.vk.client import VkClient

GROUP = 242263522
SECRET = "vk1.a.SURVEY-SECRET"


def post(i: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": i,
        "owner_id": -GROUP,
        "from_id": -GROUP,
        "date": 1786000000 + i,
        "post_type": "post",
        "text": f"секретный текст поста {i}",
        **extra,
    }


def fake_wall(posts: list[dict[str, Any]], fail_at: int | None = None) -> VkClient:
    """Стена из списка постов; offset и count берутся из запроса, как в VK."""

    def handler(request: httpx.Request) -> httpx.Response:
        q = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        offset, count = int(q["offset"]), int(q["count"])
        if fail_at is not None and offset >= fail_at:
            return httpx.Response(200, json={"error": {"error_code": 15, "error_msg": "Access denied"}})
        return httpx.Response(200, json={"response": {"count": len(posts), "items": posts[offset : offset + count]}})

    vk = VkSettings(token=SECRET, group_id=GROUP, api_url="https://api.example/method/")
    return VkClient(vk, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


def wall(n: int) -> list[dict[str, Any]]:
    # Закреп - самый старый пост, но VK отдает его первым.
    return [post(1, is_pinned=1), *[post(i) for i in range(n, 1, -1)]]


def test_walks_all_pages_and_saves_raw(tmp_path: Path) -> None:
    res = walk_wall(fake_wall(wall(7)), tmp_path / "community", page_size=3, max_pages=50)
    assert res.reported_count == 7 and len(res.posts) == 7 and res.pages == 3
    assert res.stopped == "дошли до count"
    saved = sorted((tmp_path / "community").glob("page-*.json"))
    assert len(saved) == 3
    assert json.loads(saved[0].read_text(encoding="utf-8"))["items"][0]["is_pinned"] == 1


def test_stops_on_page_limit(tmp_path: Path) -> None:
    res = walk_wall(fake_wall(wall(10)), tmp_path / "k", page_size=2, max_pages=2)
    assert len(res.posts) == 4 and "лимитом" in res.stopped


def test_error_mid_wall_keeps_what_was_read(tmp_path: Path) -> None:
    res = walk_wall(fake_wall(wall(6), fail_at=4), tmp_path / "k", page_size=2, max_pages=50)
    assert len(res.posts) == 4 and res.error is not None and "VkAuthError" in res.error


def test_report_compares_keys_and_hides_secrets(tmp_path: Path) -> None:
    full = wall(6)
    partial = full[:3]  # второй ключ видит только новые посты

    report = run_survey(
        {"community": fake_wall(partial), "service": fake_wall(full)}, tmp_path, page_size=100, max_pages=5
    )
    text = report.read_text(encoding="utf-8")
    assert "id только у service: [2, 3, 4]" in text
    assert "закрепленные (`is_pinned`): [1]" in text
    assert SECRET not in text and "секретный текст" not in text
