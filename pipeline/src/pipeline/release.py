"""Сборка сайта в releases/<время>/, проверки, атомарное переключение public_html, откат.

Раскладка (отчет о хостинге, разд. 7):
    SITE_ROOT/public_html -> releases/<время>   ссылка; сайт отдает то, на что она указывает
    SITE_ROOT/releases/<время>/                  собранный сайт и ссылка media -> ../../media
    SITE_ROOT/media/                             картинки постов

Сайт всегда отдает последний удачный релиз: пока новый не собран и не проверен, ссылка
не трогается. Переключение - rename(2) новой ссылки поверх старой: в любой момент
public_html указывает либо на старый, либо на новый релиз, промежутка нет.
"""

import logging
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pipeline.settings import Settings, SiteDirs

log = logging.getLogger("pipeline")

RELEASE_NAME = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
KEEP_RELEASES = 5
# Страниц в новом релизе может стать меньше на max(3, 20%): столько же, сколько
# удалений за раз пропускает защита сверки. Больше - скорее сломанная сборка.
PAGE_DROP_MIN = 3
PAGE_DROP_SHARE = 0.20

REPO_ROOT = Path(__file__).resolve().parents[3]


class ReleaseError(RuntimeError):
    """Релиз не собран или не прошел проверку. Сайт работает на прежнем релизе."""


def site_source() -> Path:
    path = REPO_ROOT / "site"
    if not (path / "package.json").is_file():
        raise ReleaseError(f"не найден исходник сайта: {path}/package.json")
    return path


def releases(site: SiteDirs) -> list[Path]:
    """Каталоги релизов по возрастанию времени. Только с именем-временем: чужое не трогаем."""
    if not site.releases.is_dir():
        return []
    return sorted(p for p in site.releases.iterdir() if p.is_dir() and RELEASE_NAME.match(p.name))


def current_release(site: SiteDirs) -> Path | None:
    """На какой релиз указывает public_html; None - ссылки еще нет."""
    if not site.public.is_symlink():
        return None
    target = (site.public.parent / os.readlink(site.public)).resolve()
    return target if target.is_dir() else None


def _new_release_dir(site: SiteDirs, now: int, settings: Settings) -> Path:
    base = datetime.fromtimestamp(now, settings.tz).strftime("%Y%m%d-%H%M%S")
    path = site.releases / base
    n = 1
    while path.exists():
        path = site.releases / f"{base}-{n}"
        n += 1
    return path


def _count_pages(release: Path) -> int:
    return sum(1 for _ in release.rglob("index.html"))


def check_release(release: Path, site: SiteDirs, previous: Path | None) -> int:
    """Проверки целостности до переключения. Возвращает число страниц.

    Raises:
        ReleaseError: чего-то нет или страниц резко меньше, чем в текущем релизе.
    """
    if not (release / "index.html").is_file():
        raise ReleaseError("в релизе нет index.html")
    if not (release / "sitemap-index.xml").is_file() and not (release / "sitemap-0.xml").is_file():
        raise ReleaseError("в релизе нет sitemap")
    media = release / "media"
    if not media.is_symlink() or media.resolve() != site.media.resolve():
        raise ReleaseError("в релизе нет ссылки media на каталог картинок")
    pages = _count_pages(release)
    if previous is not None:
        before = _count_pages(previous)
        allowed = max(PAGE_DROP_MIN, int(before * PAGE_DROP_SHARE))
        if before - pages > allowed:
            raise ReleaseError(f"страниц стало {pages} вместо {before} (допустимо минус {allowed})")
    return pages


def ensure_switchable(site: SiteDirs) -> None:
    """public_html должен быть ссылкой или отсутствовать. Обычный каталог - старый сайт.

    Raises:
        ReleaseError: public_html - обычный каталог: первую замену делает человек.
    """
    if site.public.exists() and not site.public.is_symlink():
        raise ReleaseError(
            f"{site.public} - обычный каталог, а не ссылка. Первая замена старого сайта делается"
            " вручную; воркер его не трогает"
        )


def switch_to(site: SiteDirs, release: Path) -> None:
    """Атомарно направить public_html на release (rename новой ссылки поверх старой).

    Raises:
        ReleaseError: public_html - обычный каталог (см. ensure_switchable).
    """
    ensure_switchable(site)
    public = site.public
    tmp = public.with_name(public.name + ".new")
    if tmp.is_symlink():
        tmp.unlink()  # хвост прошлого прерванного переключения - это всегда наша ссылка
    os.symlink(os.path.relpath(release, public.parent), tmp)
    os.replace(tmp, public)


def cleanup(site: SiteDirs, keep: int = KEEP_RELEASES) -> list[str]:
    """Удаляет старые релизы: остаются последние keep и тот, на который указывает public_html."""
    current = current_release(site)
    found = releases(site)
    removed: list[str] = []
    for old in found[: max(0, len(found) - keep)]:
        if current is not None and old.resolve() == current:
            continue
        shutil.rmtree(old)
        removed.append(old.name)
    return removed


def build_command(settings: Settings) -> list[str]:
    path = f"{settings.node_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    npm = shutil.which("npm", path=path)
    if npm is None:
        raise ReleaseError(f"npm не найден (искали в {settings.node_bin} и PATH)")
    return [npm, "run", "build"]


def build_env(settings: Settings, out_dir: Path) -> dict[str, str]:
    """Окружение сборки: только то, что нужно сайту; ключи VK сюда не попадают."""
    env = {
        "PATH": f"{settings.node_bin}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": os.environ.get("HOME", str(Path.home())),
        "ASTRO_TELEMETRY_DISABLED": "1",
        "ASTRO_OUT_DIR": str(out_dir),
        "NEWS_JSON": str(settings.data.news_json),
        "SITE_URL": settings.site_url,
        "SITE_ENV": settings.site_env,
    }
    if settings.yandex_verification:
        env["YANDEX_VERIFICATION"] = settings.yandex_verification
    if settings.google_verification:
        env["GOOGLE_VERIFICATION"] = settings.google_verification
    return env


def build_release(settings: Settings, now: int, command: Sequence[str] | None = None) -> Path:
    """Собрать, проверить, переключить, почистить. Возвращает новый релиз.

    При любой ошибке созданный этим запуском каталог удаляется, public_html не трогается,
    исключение уходит наружу (воркер оставит флаг «сайт устарел»).
    """
    site = settings.site
    site.releases.mkdir(parents=True, exist_ok=True)
    site.media.mkdir(parents=True, exist_ok=True)
    ensure_switchable(site)  # до долгой сборки, а не после
    previous = current_release(site)
    release = _new_release_dir(site, now, settings)
    cmd = list(command) if command is not None else build_command(settings)
    try:
        try:
            proc = subprocess.run(
                cmd,
                cwd=site_source(),
                env=build_env(settings, release),
                capture_output=True,
                text=True,
                timeout=settings.build_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ReleaseError(f"сборка не уложилась в {settings.build_timeout} с") from None
        if proc.returncode != 0:
            tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
            log.error("вывод сборки:\n%s", tail)
            raise ReleaseError(f"сборка сайта завершилась с кодом {proc.returncode}")
        os.symlink(os.path.relpath(site.media, release), release / "media")
        pages = check_release(release, site, previous)
        switch_to(site, release)
    except BaseException:
        if release.exists():
            shutil.rmtree(release)
        raise
    removed = cleanup(site)
    log.info(
        "релиз %s: страниц %s; public_html переключен; удалены старые: %s",
        release.name,
        pages,
        ", ".join(removed) or "нет",
    )
    return release


def rollback(site: SiteDirs, to: str | None = None) -> Path:
    """Вернуть public_html на предыдущий (или названный) релиз без пересборки.

    Raises:
        ReleaseError: некуда откатываться.
    """
    found = releases(site)
    current = current_release(site)
    if to is not None:
        target = site.releases / to
        if target not in found:
            raise ReleaseError(f"нет релиза {to}; есть: {', '.join(p.name for p in found) or 'ни одного'}")
    else:
        older = [p for p in found if current is None or p.resolve() < current]
        if not older:
            raise ReleaseError("нет более раннего релиза для отката")
        target = older[-1]
    switch_to(site, target)
    return target
