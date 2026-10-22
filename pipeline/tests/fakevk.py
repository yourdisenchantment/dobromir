"""Подменный VK: стена в памяти, отвечает на wall.get и wall.getById как настоящий."""

import copy
from typing import Any
from urllib.parse import parse_qs

import httpx

from pipeline.settings import VkSettings
from pipeline.vk.client import VkClient
from samples import GROUP, post_obj


class FakeWall:
    def __init__(self, n: int = 0) -> None:
        # Посты 1..n, у старших id дата позже.
        self.posts: dict[int, dict[str, Any]] = {
            i: post_obj(i, date=1786000000 + i * 60, attachments=[]) for i in range(1, n + 1)
        }
        self.calls: list[str] = []
        self.fail_methods: set[str] = set()  # эти методы отвечают ошибкой VK
        self.empty_by_id = False  # getById отвечает пустым списком

    # --- правка стены из теста ---

    def add(self, post_id: int, **over: Any) -> None:
        self.posts[post_id] = post_obj(post_id, date=1786000000 + post_id * 60, attachments=[], **over)

    def edit(self, post_id: int, **over: Any) -> None:
        self.posts[post_id].update(over)

    def delete(self, post_id: int) -> None:
        del self.posts[post_id]

    def pin(self, post_id: int) -> None:
        for p in self.posts.values():
            p.pop("is_pinned", None)
        self.posts[post_id]["is_pinned"] = 1

    # --- ответы ---

    def ordered(self) -> list[dict[str, Any]]:
        regular = sorted((p for p in self.posts.values() if not p.get("is_pinned")), key=lambda p: -p["date"])
        pinned = [p for p in self.posts.values() if p.get("is_pinned")]
        return pinned + regular  # закреп - первым, как у VK

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        self.calls.append(method)
        if method in self.fail_methods:
            return httpx.Response(200, json={"error": {"error_code": 10, "error_msg": "Internal server error"}})
        q = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        names = {"groups": [{"id": GROUP, "name": "Тестовая"}], "profiles": []}
        if method == "wall.get":
            offset, count = int(q["offset"]), int(q["count"])
            items = self.ordered()[offset : offset + count]
            return httpx.Response(
                200, json={"response": {"count": len(self.posts), "items": copy.deepcopy(items), **names}}
            )
        if method == "wall.getById":
            if self.empty_by_id:
                return httpx.Response(200, json={"response": {"items": [], **names}})
            ids = [int(x.split("_")[1]) for x in q["posts"].split(",")]
            items = [copy.deepcopy(self.posts[i]) for i in ids if i in self.posts]
            return httpx.Response(200, json={"response": {"items": items, **names}})
        return httpx.Response(200, json={"error": {"error_code": 3, "error_msg": "Unknown method"}})

    def http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def client(self) -> VkClient:
        vk = VkSettings(token="T", group_id=GROUP, api_url="https://api.example/method/")
        return VkClient(vk, httpx.Client(transport=httpx.MockTransport(self)), sleep=lambda s: None)
