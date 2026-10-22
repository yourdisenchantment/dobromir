"""Сырые события VK: дописываются как пришли, по файлу на день, хранятся навсегда."""

import json
import os
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RawLog:
    def __init__(self, raw_dir: Path) -> None:
        self._dir = raw_dir

    def append(self, events: Iterable[dict[str, Any]]) -> int:
        """Дописывает события и сбрасывает на диск. Возвращает, сколько записано."""
        lines = [json.dumps(e, ensure_ascii=False) + "\n" for e in events]
        if not lines:
            return 0
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"events-{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.writelines(lines)
            f.flush()
            os.fsync(f.fileno())
        return len(lines)
