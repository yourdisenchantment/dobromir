"""Настройки воркера: пути, параметры VK и сборки. Все читается из окружения.

Порядок источников (каждый следующий сильнее): `~/.env.local` (только на ноутбуке),
`<DOBROMIR_DATA>/.env` (на сервере), переменные окружения процесса.
Раскладка каталогов - отчет о хостинге, разд. 7.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DATA_VAR = "DOBROMIR_DATA"
SITE_ROOT_VAR = "SITE_ROOT"
SERVICE_TOKEN_VAR = "VK_SERVICE_TOKEN"
COMMUNITY_TOKEN_VAR = "VK_COMMUNITY_TOKEN"
GROUP_VAR = "VK_GROUP_ID"
SITE_ENV_VAR = "SITE_ENV"
LOCAL_ENV_FILE = Path.home() / ".env.local"
SITE_ENVS = ("production", "staging")

# Допущение О1 (docs/OPEN-QUESTIONS.md): канонический адрес - punycode добромир-крым.рф без www.
DEFAULT_SITE_URL = "https://xn----9sbirljdkbtdc7l.xn--p1ai"
DEFAULT_VK_API_URL = "https://api.vk.ru/method/"


@dataclass(frozen=True)
class DataDirs:
    """Непубличный каталог воркера (`~/dobromir-data` на сервере)."""

    root: Path

    @property
    def db(self) -> Path:
        """SQLite с постами и отметками синка."""
        return self.root / "db" / "dobromir.sqlite"

    @property
    def news_json(self) -> Path:
        """Экспорт для сборки сайта."""
        return self.root / "export" / "news.json"

    @property
    def worker_log(self) -> Path:
        return self.root / "logs" / "worker.log"

    @property
    def status_json(self) -> Path:
        """Состояние последнего запуска, без секретов (допущение: в корне каталога данных)."""
        return self.root / "status.json"

    @property
    def env_file(self) -> Path:
        """Секреты и настройки сервера."""
        return self.root / ".env"

    # Переходное: нужно нынешним разбору и экспорту по папкам, уходит в P1-3 вместе с ними.
    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def content(self) -> Path:
        return self.root / "content"


@dataclass(frozen=True)
class SiteDirs:
    """Папка сайта Beget (`~/a978879k.beget.tech`): все, что отдает веб-сервер."""

    root: Path

    @property
    def media(self) -> Path:
        """Скачанные картинки постов."""
        return self.root / "media"

    @property
    def releases(self) -> Path:
        """Собранные релизы, по папке на сборку."""
        return self.root / "releases"

    @property
    def public(self) -> Path:
        """Ссылка на текущий релиз."""
        return self.root / "public_html"


@dataclass(frozen=True)
class VkSettings:
    """Доступ к VK. Токен скрыт из repr, чтобы не попасть в лог или трейсбек."""

    token: str = field(repr=False)
    group_id: int
    api_url: str


@dataclass(frozen=True)
class Settings:
    data: DataDirs
    site: SiteDirs
    vk_api_url: str
    vk_group_id: int | None
    vk_service_token: str | None = field(repr=False)
    vk_community_token: str | None = field(repr=False)
    vk_window: int
    vk_page_size: int
    vk_by_id_batch: int
    max_builds_per_day: int
    reconcile_after_hour: int
    tz_name: str
    site_url: str
    site_env: str
    node_bin: Path

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    def vk(self, key: str = "service") -> VkSettings:
        """Доступ к VK. Нужен воркеру, не каждой команде.

        Стену (`wall.get`, `wall.getById`) читает только сервисный ключ: ключ
        сообщества получает ошибку 27 (проверено 2026-10-22, OPEN-QUESTIONS, О2).

        Args:
            key: "community" или "service".

        Raises:
            RuntimeError: нет нужного ключа или id группы.
        """
        tokens = {
            "community": (self.vk_community_token, COMMUNITY_TOKEN_VAR, "ключ сообщества"),
            "service": (self.vk_service_token, SERVICE_TOKEN_VAR, "сервисный ключ приложения"),
        }
        if key not in tokens:
            raise ValueError(f"key должен быть community или service, получено {key!r}")
        token, var, title = tokens[key]
        if not token:
            raise RuntimeError(f"{var} не задана: нужен {title} VK")
        if self.vk_group_id is None:
            raise RuntimeError(f"{GROUP_VAR} не задана: нужен id группы без минуса")
        return VkSettings(token=token, group_id=self.vk_group_id, api_url=self.vk_api_url)


def read_env_file(path: Path) -> dict[str, str]:
    """Файл `KEY=VALUE`: пустые строки и `#` пропускаются, `export ` и кавычки снимаются. Нет файла - пусто."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def load_env(environ: Mapping[str, str] | None = None, local_file: Path = LOCAL_ENV_FILE) -> dict[str, str]:
    """Сводит три источника: `~/.env.local`, затем `<DOBROMIR_DATA>/.env`, затем окружение процесса."""
    process_env = dict(os.environ if environ is None else environ)
    values = read_env_file(local_file)
    # Где лежит .env сервера, узнаем из уже известного: окружение процесса сильнее файла.
    data_root = process_env.get(DATA_VAR) or values.get(DATA_VAR)
    if data_root and Path(data_root).is_absolute():
        values.update(read_env_file(DataDirs(Path(data_root)).env_file))
    values.update(process_env)
    return values


def _abs_path(env: Mapping[str, str], name: str) -> Path:
    value = env.get(name)
    if not value:
        raise RuntimeError(f"{name} не задана: укажите абсолютный путь")
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeError(f"{name} должна быть абсолютным путем, получено {value!r}")
    return path


def _int(env: Mapping[str, str], name: str, default: int, low: int, high: int | None = None) -> int:
    value = env.get(name)
    if value is None or value == "":
        return default
    if not value.strip().isdecimal():
        raise RuntimeError(f"{name} должна быть целым числом, получено {value!r}")
    number = int(value)
    if number < low or (high is not None and number > high):
        bounds = f"от {low}" + (f" до {high}" if high is not None else "")
        raise RuntimeError(f"{name} должна быть {bounds}, получено {number}")
    return number


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Читает и проверяет все настройки. Ошибка - сразу и с именем переменной.

    Raises:
        RuntimeError: обязательная переменная не задана или значение недопустимо.
    """
    env = load_env() if env is None else env

    group = env.get(GROUP_VAR) or None
    if group is not None and not group.isdecimal():
        raise RuntimeError(f"{GROUP_VAR} должна быть числом без минуса, получено {group!r}")

    tz_name = env.get("TZ_NAME") or "Europe/Simferopol"
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise RuntimeError(f"TZ_NAME: неизвестный часовой пояс {tz_name!r}") from None

    # Без значения по умолчанию: ошибка в любую сторону вредна (noindex на боевом или индексация тестового).
    site_env = env.get(SITE_ENV_VAR, "")
    if site_env not in SITE_ENVS:
        raise RuntimeError(f"{SITE_ENV_VAR} должна быть production или staging, получено {site_env!r}")

    site_url = (env.get("SITE_URL") or DEFAULT_SITE_URL).rstrip("/")
    if not site_url.startswith("https://"):
        raise RuntimeError(f"SITE_URL должен начинаться с https://, получено {site_url!r}")

    return Settings(
        data=DataDirs(_abs_path(env, DATA_VAR)),
        site=SiteDirs(_abs_path(env, SITE_ROOT_VAR)),
        vk_api_url=env.get("VK_API_URL") or DEFAULT_VK_API_URL,
        vk_group_id=None if group is None else int(group),
        vk_service_token=env.get(SERVICE_TOKEN_VAR) or None,
        vk_community_token=env.get(COMMUNITY_TOKEN_VAR) or None,
        vk_window=_int(env, "VK_WINDOW", 50, low=1),
        vk_page_size=_int(env, "VK_PAGE_SIZE", 100, low=1, high=100),
        vk_by_id_batch=_int(env, "VK_BY_ID_BATCH", 100, low=1, high=100),
        max_builds_per_day=_int(env, "MAX_BUILDS_PER_DAY", 4, low=1),
        reconcile_after_hour=_int(env, "RECONCILE_AFTER_HOUR", 3, low=0, high=23),
        tz_name=tz_name,
        site_url=site_url,
        site_env=site_env,
        node_bin=Path(env["NODE_BIN"]) if env.get("NODE_BIN") else Path.home() / "opt" / "node" / "bin",
    )
