"""Сборка релиза, проверки, атомарное переключение public_html, чистка и откат."""

import dataclasses
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pipeline.release import (
    ReleaseError,
    build_release,
    cleanup,
    current_release,
    releases,
    rollback,
    switch_to,
)
from pipeline.settings import Settings, load_settings

TZ = ZoneInfo("Europe/Simferopol")
FAKE = str(Path(__file__).parent / "fake_build.py")
SECRET = "vk1.a.RELEASE-SECRET"


def at(day: int, hour: int, minute: int = 0, second: int = 0) -> int:
    return int(datetime(2026, 10, day, hour, minute, second, tzinfo=TZ).timestamp())


def settings_at(tmp_path: Path) -> Settings:
    s = load_settings(
        {
            "DOBROMIR_DATA": str(tmp_path / "data"),
            "SITE_ROOT": str(tmp_path / "site"),
            "SITE_ENV": "production",
            "VK_SERVICE_TOKEN": SECRET,
            "YANDEX_VERIFICATION": "ya123",
        }
    )
    s.data.news_json.parent.mkdir(parents=True, exist_ok=True)
    s.data.news_json.write_text("{}", encoding="utf-8")  # подменная сборка его не читает
    return s


def fake(mode: str = "ok", pages: int = 10) -> list[str]:
    return [sys.executable, FAKE, mode, str(pages)]


def test_build_switches_public_html(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    rel = build_release(s, at(23, 10), command=fake())
    assert rel.name == "20261023-100000"
    assert s.site.public.is_symlink() and current_release(s.site) == rel.resolve()
    assert os.readlink(s.site.public) == "releases/20261023-100000"  # относительная ссылка
    assert (s.site.public / "index.html").read_text(encoding="utf-8") == "<html>главная</html>"
    assert (rel / "media").resolve() == s.site.media.resolve()


@pytest.mark.parametrize(
    ("mode", "message"), [("no-index", "index.html"), ("no-sitemap", "sitemap"), ("fail", "кодом 1")]
)
def test_bad_release_keeps_old_site(tmp_path: Path, mode: str, message: str) -> None:
    s = settings_at(tmp_path)
    good = build_release(s, at(23, 10), command=fake())
    (s.site.media / "photo.jpg").write_bytes(b"x")
    with pytest.raises(ReleaseError, match=message):
        build_release(s, at(23, 11), command=fake(mode))
    assert current_release(s.site) == good.resolve()  # сайт на прежнем релизе
    assert [p.name for p in releases(s.site)] == [good.name]  # неудачный каталог убран
    assert (s.site.media / "photo.jpg").is_file()  # картинки не задеты удалением релиза


def test_timeout(tmp_path: Path) -> None:
    s = dataclasses.replace(settings_at(tmp_path), build_timeout=1)
    with pytest.raises(ReleaseError, match="не уложилась"):
        build_release(s, at(23, 10), command=fake("slow"))
    assert releases(s.site) == [] and not s.site.public.exists()


def test_sharp_page_drop_refused(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    good = build_release(s, at(23, 10), command=fake(pages=30))
    with pytest.raises(ReleaseError, match="страниц стало 20 вместо 30"):
        build_release(s, at(23, 11), command=fake(pages=20))
    assert current_release(s.site) == good.resolve()
    build_release(s, at(23, 12), command=fake(pages=24))  # минус 6 - в пределах max(3, 20%)


def test_real_public_html_directory_is_never_touched(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    s.site.public.mkdir(parents=True)
    (s.site.public / "wp-config.php").write_text("старый сайт", encoding="utf-8")
    with pytest.raises(ReleaseError, match="обычный каталог"):
        build_release(s, at(23, 10), command=fake())
    assert (s.site.public / "wp-config.php").read_text(encoding="utf-8") == "старый сайт"
    assert releases(s.site) == []


def test_keeps_five_releases(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    built = [build_release(s, at(23, 10, i), command=fake()).name for i in range(7)]
    assert [p.name for p in releases(s.site)] == built[-5:]
    assert current_release(s.site) == (s.site.releases / built[-1]).resolve()


def test_cleanup_keeps_current_even_if_old(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    built = [build_release(s, at(23, 10, i), command=fake()).name for i in range(5)]
    rollback(s.site, to=built[0])
    for i in range(6, 8):
        (s.site.releases / f"20261023-1{i}0000").mkdir()  # еще новые, без переключения
    assert cleanup(s.site) == [built[1]]  # самый старый текущий остался, удален следующий
    names = [p.name for p in releases(s.site)]
    assert built[0] in names and len(names) == 6  # 5 последних + текущий старый


def test_foreign_dirs_in_releases_untouched(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    s.site.releases.mkdir(parents=True)
    (s.site.releases / "мое-не-трогать").mkdir()
    for i in range(7):
        build_release(s, at(23, 10, i), command=fake())
    assert (s.site.releases / "мое-не-трогать").is_dir()


def test_same_second_builds_get_distinct_names(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    a = build_release(s, at(23, 10), command=fake())
    b = build_release(s, at(23, 10), command=fake())
    assert a.name == "20261023-100000" and b.name == "20261023-100000-1"


def test_many_builds_in_one_second_keep_order(tmp_path: Path) -> None:
    """Номер за ту же секунду растет и после чистки; «-10» новее «-9», откат идет на «-10»."""
    s = settings_at(tmp_path)
    built = [build_release(s, at(23, 10), command=fake()).name for _ in range(12)]
    assert built[0] == "20261023-100000" and built[11] == "20261023-100000-11"
    assert len(set(built)) == 12
    assert [p.name for p in releases(s.site)] == built[-5:]
    assert rollback(s.site).name == "20261023-100000-10"


def test_rollback_refuses_unknown_current(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    build_release(s, at(23, 10), command=fake())
    (s.site.releases / "ручной").mkdir()
    switch_to(s.site, s.site.releases / "ручной")
    with pytest.raises(ReleaseError, match="укажите --to"):
        rollback(s.site)


def test_rollback(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    first = build_release(s, at(23, 10), command=fake())
    second = build_release(s, at(23, 11), command=fake())
    assert rollback(s.site) == first and current_release(s.site) == first.resolve()
    with pytest.raises(ReleaseError, match="нет более раннего"):
        rollback(s.site)
    assert rollback(s.site, to=second.name) == second
    with pytest.raises(ReleaseError, match="нет релиза"):
        rollback(s.site, to="20200101-000000")


def test_switch_is_atomic(tmp_path: Path) -> None:
    """Пока ссылка переключается туда-обратно, читатель ни разу не видит «нет сайта»."""
    s = settings_at(tmp_path)
    a = build_release(s, at(23, 10), command=fake())
    b = build_release(s, at(23, 11), command=fake())
    stop = threading.Event()
    misses: list[str] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                (s.site.public / "index.html").read_bytes()
            except OSError as exc:
                misses.append(type(exc).__name__)

    t = threading.Thread(target=reader)
    t.start()
    try:
        for i in range(300):
            switch_to(s.site, a if i % 2 else b)
    finally:
        stop.set()
        t.join()
    assert misses == []


def test_build_env_has_no_vk_keys_and_passes_site_settings(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    rel = build_release(s, at(23, 10), command=fake("env"))
    env = (rel / "env.txt").read_text(encoding="utf-8")
    assert SECRET not in env and "VK_" not in env
    assert f"NEWS_JSON={s.data.news_json}" in env and "SITE_ENV=production" in env
    assert "ASTRO_TELEMETRY_DISABLED=1" in env and "YANDEX_VERIFICATION=ya123" in env
    assert f"ASTRO_OUT_DIR={rel}" in env


def test_no_news_json_refused_before_build(tmp_path: Path) -> None:
    """Без news.json боевая сборка не начинается: иначе пустой сайт или примеры."""
    s = settings_at(tmp_path)
    s.data.news_json.unlink()
    with pytest.raises(ReleaseError, match="python -m pipeline export"):
        build_release(s, at(23, 10), command=fake())
    assert releases(s.site) == [] and not s.site.public.exists()


def test_trial_build_does_not_switch(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    live = build_release(s, at(23, 10), command=fake())
    trial = build_release(s, at(23, 11), command=fake(), switch=False)
    assert current_release(s.site) == live.resolve()  # сайт на прежнем
    assert (trial / "index.html").is_file() and (trial / "media").is_symlink()
    assert rollback(s.site, to=trial.name) == trial  # включается командой отката
    assert current_release(s.site) == trial.resolve()


def test_trial_build_next_to_old_site_directory(tmp_path: Path) -> None:
    """Первый деплой: public_html - еще каталог старого сайта. Пробная сборка можно, переключение нет."""
    s = settings_at(tmp_path)
    s.site.public.mkdir(parents=True)
    (s.site.public / "index.php").write_text("старый сайт", encoding="utf-8")
    trial = build_release(s, at(23, 10), command=fake(), switch=False)
    assert (trial / "index.html").is_file()
    assert (s.site.public / "index.php").read_text(encoding="utf-8") == "старый сайт"
    with pytest.raises(ReleaseError, match="обычный каталог"):
        rollback(s.site, to=trial.name)
    assert not s.site.public.is_symlink()


def test_failed_trial_build_cleans_up(tmp_path: Path) -> None:
    s = settings_at(tmp_path)
    with pytest.raises(ReleaseError):
        build_release(s, at(23, 10), command=fake("no-index"), switch=False)
    assert releases(s.site) == []
