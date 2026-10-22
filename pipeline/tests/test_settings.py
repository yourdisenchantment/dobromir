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
    if name == "SITE_ROOT":  # у каталога данных есть значение по умолчанию, у папки сайта нет
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
    for key in ("community", "service"):
        assert SECRET not in repr(s.vk(key))
    assert s.vk().token == SECRET  # по умолчанию - сервисный: только он читает стену
    assert s.vk("community").token == SECRET + "-group"
    assert s.vk().group_id == 242263522


def test_vk_requires_token_and_group(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="VK_SERVICE_TOKEN"):
        load_settings(base_env(tmp_path, VK_GROUP_ID="1", VK_COMMUNITY_TOKEN=SECRET)).vk()
    with pytest.raises(RuntimeError, match="VK_COMMUNITY_TOKEN"):
        load_settings(base_env(tmp_path, VK_GROUP_ID="1", VK_SERVICE_TOKEN=SECRET)).vk("community")
    with pytest.raises(RuntimeError, match="VK_GROUP_ID"):
        load_settings(base_env(tmp_path, VK_SERVICE_TOKEN=SECRET)).vk()
    with pytest.raises(ValueError, match="community или service"):
        load_settings(base_env(tmp_path, VK_GROUP_ID="1", VK_COMMUNITY_TOKEN=SECRET)).vk("user")


def test_env_sources_order(tmp_path: Path) -> None:
    """Окружение процесса сильнее <data>/.env; каталог данных - из DOBROMIR_DATA."""
    data = tmp_path / "data"
    data.mkdir()
    (data / ".env").write_text(
        '# комментарий\nexport VK_WINDOW="20"\nVK_GROUP_ID=2\nDOBROMIR_DATA=/куда-то/еще\n', encoding="utf-8"
    )
    env = load_env(environ={"DOBROMIR_DATA": str(data), "VK_GROUP_ID": "3"}, home=tmp_path / "home")
    assert env["VK_WINDOW"] == "20"  # из файла, кавычки и export сняты
    assert env["VK_GROUP_ID"] == "3"  # окружение процесса сильнее файла
    assert env["DOBROMIR_DATA"] == str(data)  # строка в самом .env каталог не меняет


def test_default_data_dir_is_home_dobromir_data(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "dobromir-data").mkdir(parents=True)
    (home / "dobromir-data" / ".env").write_text("VK_GROUP_ID=7\n", encoding="utf-8")
    env = load_env(environ={}, home=home)
    assert env["DOBROMIR_DATA"] == str(home / "dobromir-data")
    assert env["VK_GROUP_ID"] == "7"


def test_other_files_are_not_read(tmp_path: Path) -> None:
    """~/.env.local с чужими ключами проект больше не читает."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env.local").write_text("VK_GROUP_ID=99\nOTHER_SECRET=x\n", encoding="utf-8")
    env = load_env(environ={"A": "1"}, home=home)
    assert env == {"A": "1", "DOBROMIR_DATA": str(home / "dobromir-data")}


def test_settings_without_data_var_use_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    env = base_env(tmp_path)
    del env["DOBROMIR_DATA"]
    assert load_settings(env).data.root == tmp_path / "dobromir-data"
