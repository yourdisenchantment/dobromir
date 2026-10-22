"""Образцы постов VK в форме ответа wall.get (поля урезаны до используемых)."""

from typing import Any

GROUP = 49938199


def photo_att(photo_id: int) -> dict[str, Any]:
    return {
        "type": "photo",
        "photo": {
            "id": photo_id,
            "owner_id": -GROUP,
            "sizes": [
                {"type": "s", "url": f"https://pp.example/{photo_id}_s.jpg", "width": 75, "height": 50},
                {"type": "w", "url": f"https://pp.example/{photo_id}_w.jpg", "width": 2560, "height": 1707},
                {"type": "m", "url": f"https://pp.example/{photo_id}_m.jpg", "width": 130, "height": 87},
            ],
        },
    }


def post_obj(post_id: int = 101, **over: Any) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "id": post_id,
        "owner_id": -GROUP,
        "from_id": -GROUP,
        "date": 1786000000,  # 2026-08-06 07:06:40 UTC
        "post_type": "post",
        "text": "Открытие центра\nПриходите завтра! #мероприятия #Добромир@dobromir_crimea #мероприятия",
        "attachments": [
            photo_att(1),
            photo_att(2),
            {"type": "video", "video": {"id": 5, "owner_id": -GROUP}},
            {"type": "link", "link": {"url": "https://example.org/a", "title": "Подробнее"}},
        ],
        **over,
    }
    return obj
