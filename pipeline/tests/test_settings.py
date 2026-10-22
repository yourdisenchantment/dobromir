from pathlib import Path

import pytest

from pipeline.settings import DEFAULT_SITE_URL, load_env, load_settings

SECRET = "vk1.a.SECRET-SERVICE-TOKEN"


def base_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        "DOBROMIR_DATA": str(tmp_path / "data"),
        "SITE_ROOT": str(tmp_path / "site"),
        "SITE_ENV": "production",
    }
    env.update(extra)
    return env


def test_layout(tmp_path: Path) -> None:
    s = load_settings(base_env(tmp_path))
    data, site = tmp_path / "data", tmp_path / "site"
    assert s.data.db == data / "db" / "dobromir.sqlite"
    assert s.data.news_json == data / "export" / "news.json"
    assert s.data.worker_log == data / "logs" / "worker.log"
    assert s.data.status_json == data / "status.json"
    assert s.data.env_file == data / ".env"
    assert s.site.media == site / "media"
    assert s.site.releases == site / "releases"
    assert s.site.public == site / "public_html"


def test_defaults(tmp_path: Path) -> None:
    s = load_settings(base_env(tmp_path))
    assert s.vk_api_url == "https://api.vk.ru/method/"
    assert (s.vk_window, s.vk_page_size, s.vk_by_id_batch) == (50, 100, 100)
    assert (s.max_builds_per_day, s.reconcile_after_hour) == (4, 3)
    assert s.tz_name == "Europe/Simferopol" and str(s.tz) == "Europe/Simferopol"
    assert s.site_url == DEFAULT_SITE_URL == "https://xn----9sbirljdkbtdc7l.xn--p1ai"
    assert s.node_bin == Path.home() / "opt" / "node" / "bin"
    assert s.vk_group_id is None and s.vk_service_token is None and s.vk_community_token is None


def test_overrides(tmp_path: Path) -> None:
    s = load_settings(
        base_env(
            tmp_path,
            VK_WINDOW="20",
            MAX_BUILDS_PER_DAY="2",
            RECONCILE_AFTER_HOUR="0",
            SITE_URL="https://example.test/",
            SITE_ENV="staging",
            NODE_BIN="/opt/node/bin",
            VK_API_URL="https://api.vk.com/method/",
        )
    )
    assert (s.vk_window, s.max_builds_per_day, s.reconcile_after_hour) == (20, 2, 0)
    assert s.site_url == "https://example.test"  # слэш в конце убирается
    assert s.site_env == "staging"
    assert s.node_bin == Path("/opt/node/bin")
    assert s.vk_api_url == "https://api.vk.com/method/"


@pytest.mark.parametrize("name", ["DOBROMIR_DATA", "SITE_ROOT"])
def test_required_paths(tmp_path: Path, name: str) -> None:
    env = base_env(tmp_path)
    del env[name]
    with pytest.raises(RuntimeError, match=name):
        load_settings(env)
    env[name] = "relative/dir"
    with pytest.raises(RuntimeError, match="абсолютным"):
        load_settings(env)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("VK_WINDOW", "много"),
        ("VK_WINDOW", "-5"),
        ("VK_WINDOW", "0"),
        ("MAX_BUILDS_PER_DAY", "4.5"),
        ("MAX_BUILDS_PER_DAY", "0"),
        ("VK_PAGE_SIZE", "101"),
        ("RECONCILE_AFTER_HOUR", "24"),
        ("VK_GROUP_ID", "-242263522"),
    ],
)
def test_bad_numbers(tmp_path: Path, name: str, value: str) -> None:
    with pytest.raises(RuntimeError, match=name):
        load_settings(base_env(tmp_path, **{name: value}))


@pytest.mark.parametrize("value", ["", "prod", "Production"])
def test_site_env_must_be_explicit(tmp_path: Path, value: str) -> None:
    with pytest.raises(RuntimeError, match="SITE_ENV"):
        load_settings(base_env(tmp_path, SITE_ENV=value))


def test_bad_values(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="TZ_NAME"):
        load_settings(base_env(tmp_path, TZ_NAME="Europe/Nowhere"))
    with pytest.raises(RuntimeError, match="SITE_URL"):
        load_settings(base_env(tmp_path, SITE_URL="http://example.test"))


def test_tokens_not_in_repr(tmp_path: Path) -> None:
    s = load_settings(
        base_env(tmp_path, VK_SERVICE_TOKEN=SECRET, VK_COMMUNITY_TOKEN=SECRET + "-group", VK_GROUP_ID="242263522")
    )
    assert SECRET not in repr(s)
    vk = s.vk()
    assert vk.token == SECRET and vk.group_id == 242263522
    assert SECRET not in repr(vk)


def test_vk_requires_token_and_group(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="VK_SERVICE_TOKEN"):
        load_settings(base_env(tmp_path, VK_GROUP_ID="1")).vk()
    with pytest.raises(RuntimeError, match="VK_GROUP_ID"):
        load_settings(base_env(tmp_path, VK_SERVICE_TOKEN=SECRET)).vk()


def test_env_sources_order(tmp_path: Path) -> None:
    """Окружение процесса сильнее <data>/.env, а тот сильнее ~/.env.local."""
    data = tmp_path / "data"
    data.mkdir()
    local = tmp_path / ".env.local"
    local.write_text(
        f'# комментарий\nexport DOBROMIR_DATA="{data}"\nVK_WINDOW=10\nVK_GROUP_ID=1\nMAX_BUILDS_PER_DAY=7\n',
        encoding="utf-8",
    )
    (data / ".env").write_text("VK_WINDOW=20\nVK_GROUP_ID=2\n", encoding="utf-8")
    env = load_env(environ={"VK_GROUP_ID": "3"}, local_file=local)
    assert env["VK_WINDOW"] == "20"  # .env сервера сильнее локального файла
    assert env["VK_GROUP_ID"] == "3"  # окружение процесса сильнее обоих
    assert env["MAX_BUILDS_PER_DAY"] == "7"  # чего нет выше, берется из локального
    assert env["DOBROMIR_DATA"] == str(data)


def test_env_files_are_optional(tmp_path: Path) -> None:
    env = load_env(environ={"A": "1"}, local_file=tmp_path / "нет-такого")
    assert env == {"A": "1"}
