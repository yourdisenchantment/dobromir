"""Вызовы методов VK API.

Различаем три исхода, потому что воркер реагирует на них по-разному
(отчет о хостинге, разд. 9): сеть - повторить позже, ключ - сообщить человеку,
прочие ошибки VK - записать и не считать пост удаленным.
"""

import time
from collections.abc import Callable
from typing import Any, Literal

import httpx

from pipeline.settings import VkSettings

API_VERSION = "5.199"

# Коды, при которых проблема в ключе или его правах, а не в запросе
# (5 - авторизация, 15 - доступ запрещен, 17 - нужна валидация, 27 - метод недоступен
# с ключом сообщества, 28 - метод недоступен с ключом приложения). Сверено с
# vk-api/vk-api-spravochnik.md не полностью: допущение, уточняется на живых ответах.
AUTH_CODES = frozenset({5, 15, 17, 27, 28})
RETRY_PAUSES = (2.0, 4.0, 8.0)

TokenIn = Literal["header", "body"]


class VkError(RuntimeError):
    """Любая ошибка обращения к VK. В сообщении нет ключа и адресов запросов."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class VkNetworkError(VkError):
    """Сеть, таймаут, 5xx или не-JSON: ответа VK нет. Повторить позже."""


class VkAuthError(VkError):
    """Ключ отклонен или не имеет прав. Без человека не исправится."""


class VkApiError(VkError):
    """VK ответил ошибкой, не связанной с ключом."""


class VkClient:
    def __init__(
        self,
        vk: VkSettings,
        http: httpx.Client,
        token_in: TokenIn = "header",
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 30,
    ) -> None:
        """
        Args:
            vk: ключ, группа и адрес API.
            http: общий HTTP-клиент; в тестах - с подменным транспортом.
            token_in: "header" - `Authorization: Bearer`, "body" - параметр
                `access_token` в теле POST. В адрес запроса ключ не попадает никогда.
            sleep: пауза между повторами; в тестах подменяется.
            timeout: таймаут одного запроса, секунды.
        """
        self._vk = vk
        self._http = http
        self._token_in = token_in
        self._sleep = sleep
        self._timeout = timeout

    @property
    def owner_id(self) -> int:
        """Владелец стены группы: id группы со знаком минус."""
        return -self._vk.group_id

    def call(self, method: str, **params: Any) -> Any:
        """Один метод VK; сетевые сбои повторяются с паузами 2, 4, 8 с.

        Raises:
            VkNetworkError: сеть так и не ответила.
            VkAuthError: ошибка ключа или прав.
            VkApiError: прочая ошибка VK.
        """
        data = {**params, "v": API_VERSION}
        headers = {}
        if self._token_in == "header":
            headers["Authorization"] = f"Bearer {self._vk.token}"
        else:
            data["access_token"] = self._vk.token
        last: VkNetworkError | None = None
        for attempt in range(len(RETRY_PAUSES) + 1):
            if attempt:
                self._sleep(RETRY_PAUSES[attempt - 1])
            try:
                return self._once(method, data, headers)
            except VkNetworkError as exc:
                last = exc
        assert last is not None
        raise last

    def _once(self, method: str, data: dict[str, Any], headers: dict[str, str]) -> Any:
        try:
            resp = self._http.post(self._vk.api_url + method, data=data, headers=headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            # Текст исключения httpx не пробрасываем: в нем бывает запрос целиком.
            raise VkNetworkError(f"{method}: сбой сети ({type(exc).__name__})") from None
        if resp.status_code >= 500:
            raise VkNetworkError(f"{method}: HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise VkApiError(f"{method}: HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError:
            raise VkNetworkError(f"{method}: ответ не JSON") from None
        if not isinstance(body, dict):
            raise VkApiError(f"{method}: неожиданный ответ")
        if "error" in body:
            err = body["error"] if isinstance(body["error"], dict) else {}
            code = err.get("error_code")
            text = f"{method}: [{code}] {err.get('error_msg', '')}"
            raise (VkAuthError if code in AUTH_CODES else VkApiError)(text, code)
        if "response" not in body:
            raise VkApiError(f"{method}: нет поля response")
        return body["response"]

    def wall_get(self, offset: int = 0, count: int = 100, extended: bool = False) -> dict[str, Any]:
        """Страница стены группы, новые первыми (закрепленный пост - первым, вне хронологии).

        Returns:
            Ответ VK как есть: `count` (всего постов) и `items`; при extended - еще
            `profiles` и `groups` (имена авторов репостов).
        """
        resp = self.call(
            "wall.get",
            owner_id=self.owner_id,
            offset=offset,
            count=count,
            filter="all",
            extended=int(extended),
        )
        if not isinstance(resp, dict) or not isinstance(resp.get("items"), list):
            raise VkApiError("wall.get: в ответе нет списка items")
        return resp

    def wall_get_by_id(self, post_ids: list[int], extended: bool = False) -> dict[str, Any]:
        """Посты группы по их id. Чего нет в ответе - VK не отдал (удален, скрыт или нет прав).

        Returns:
            Ответ в той же форме, что у `wall_get`: `items`, при extended - `groups` и
            `profiles`. В 5.199 VK отдает либо список, либо объект с items - приводим к объекту.
        """
        if not post_ids:
            return {"items": []}
        resp = self.call(
            "wall.getById",
            posts=",".join(f"{self.owner_id}_{i}" for i in post_ids),
            extended=int(extended),
        )
        if isinstance(resp, list):
            resp = {"items": resp}
        if not isinstance(resp, dict) or not isinstance(resp.get("items"), list):
            raise VkApiError("wall.getById: неожиданная форма ответа")
        return resp
