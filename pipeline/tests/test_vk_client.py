import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from pipeline.settings import VkSettings
from pipeline.vk.client import VkApiError, VkAuthError, VkClient, VkNetworkError

SECRET = "vk1.a.SECRET-TOKEN-NOT-FOR-LOGS"
VK = VkSettings(token=SECRET, group_id=242263522, api_url="https://api.example/method/")


class Recorder:
    """Подменный VK: отдает заготовленные ответы по очереди и запоминает запросы."""

    def __init__(self, *answers: httpx.Response | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def client(rec: Recorder, token_in: Any = "header", pauses: list[float] | None = None) -> VkClient:
    sleep: Callable[[float], None] = pauses.append if pauses is not None else lambda s: None
    return VkClient(VK, httpx.Client(transport=httpx.MockTransport(rec)), token_in=token_in, sleep=sleep)


def ok(response: Any) -> httpx.Response:
    return httpx.Response(200, json={"response": response})


def vk_error(code: int, msg: str = "x") -> httpx.Response:
    return httpx.Response(200, json={"error": {"error_code": code, "error_msg": msg}})


def test_token_in_header_not_in_url_or_body() -> None:
    rec = Recorder(ok({"count": 0, "items": []}))
    client(rec).wall_get()
    req = rec.requests[0]
    assert req.headers["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in str(req.url)
    assert SECRET.encode() not in req.content
    assert b"owner_id=-242263522" in req.content and b"v=5.199" in req.content


def test_token_in_body_not_in_url_or_header() -> None:
    rec = Recorder(ok({"count": 0, "items": []}))
    client(rec, token_in="body").wall_get()
    req = rec.requests[0]
    assert "Authorization" not in req.headers
    assert SECRET not in str(req.url)
    assert b"access_token=" in req.content


@pytest.mark.parametrize("code", [5, 15, 17, 27, 28])
def test_auth_errors(code: int) -> None:
    with pytest.raises(VkAuthError) as exc:
        client(Recorder(vk_error(code))).wall_get()
    assert exc.value.code == code
    assert SECRET not in str(exc.value)


def test_other_vk_error_is_api_error_and_not_retried() -> None:
    rec = Recorder(vk_error(100, "One of the parameters specified was missing or invalid"))
    with pytest.raises(VkApiError, match=r"\[100\]"):
        client(rec).wall_get()
    assert len(rec.requests) == 1


def test_network_failures_retry_then_succeed() -> None:
    pauses: list[float] = []
    rec = Recorder(httpx.ConnectError("нет сети"), httpx.Response(502), ok({"count": 1, "items": [{}]}))
    assert client(rec, pauses=pauses).wall_get()["count"] == 1
    assert pauses == [2.0, 4.0]


def test_network_failures_give_up_after_retries(caplog: pytest.LogCaptureFixture) -> None:
    pauses: list[float] = []
    rec = Recorder(*[httpx.ReadTimeout("медленно") for _ in range(4)])
    with caplog.at_level(logging.DEBUG), pytest.raises(VkNetworkError) as exc:
        client(rec, pauses=pauses).wall_get()
    assert pauses == [2.0, 4.0, 8.0] and len(rec.requests) == 4
    assert SECRET not in str(exc.value) and SECRET not in caplog.text


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(200, content=b"<html>"), httpx.Response(200, json=[1, 2]), httpx.Response(200, json={})],
)
def test_garbage_answers(answer: httpx.Response) -> None:
    with pytest.raises((VkNetworkError, VkApiError)):
        client(Recorder(answer, answer, answer, answer)).wall_get()


def test_wall_get_requires_items() -> None:
    with pytest.raises(VkApiError, match="items"):
        client(Recorder(ok({"count": 3}))).wall_get()


@pytest.mark.parametrize("shape", ["list", "object"])
def test_get_by_id_both_shapes(shape: str) -> None:
    posts = [{"id": 1}, {"id": 3}]
    rec = Recorder(ok(posts if shape == "list" else {"items": posts}))
    assert client(rec).wall_get_by_id([1, 2, 3])["items"] == posts
    assert b"posts=-242263522_1%2C-242263522_2%2C-242263522_3" in rec.requests[0].content


def test_get_by_id_empty_list_makes_no_request() -> None:
    rec = Recorder()
    assert client(rec).wall_get_by_id([]) == {"items": []}
    assert rec.requests == []
