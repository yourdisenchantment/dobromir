"""Вызовы методов VK API ключом сообщества."""

from typing import Any

import httpx

API_URL = "https://api.vk.ru/method/"
API_VERSION = "5.199"


class VkError(RuntimeError):
    """Ошибка VK. В сообщении нет токена и адресов с ключами."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class VkClient:
    def __init__(self, token: str, http: httpx.Client) -> None:
        self._token = token
        self._http = http

    def call(self, method: str, **params: Any) -> Any:
        """Один вызов. VK отдает 200 и на ошибку - она лежит в теле ответа."""
        try:
            resp = self._http.post(
                API_URL + method,
                headers={"Authorization": f"Bearer {self._token}"},
                data={**params, "v": API_VERSION},
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Текст исходной ошибки не пробрасываем: в нем может быть адрес запроса.
            raise VkError(f"{method}: сбой запроса ({type(exc).__name__})") from None
        if "error" in body:
            err = body["error"]
            raise VkError(f"{method}: [{err.get('error_code')}] {err.get('error_msg')}", err.get("error_code"))
        return body["response"]
