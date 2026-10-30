# pipeline/src/pipeline/release.py
"""Сборка сайта в releases/<время>/, проверки, атомарное переключение public_html, откат.

Раскладка (отчет о хостинге, разд. 7):
    SITE_ROOT/public_html -> releases/<время>   ссылка; сайт отдает то, на что она указывает
    SITE_ROOT/releases/<время>/                  собранный сайт и ссылка media -> ../../media
    SITE_ROOT/media/                             картинки постов

Сайт всегда отдает последний удачный релиз: пока новый не собран и не проверен, ссылка
не трогается. Переключение - rename(2) новой ссылки поверх старой: в любой момент
public_html указывает либо на старый, либо на новый релиз, промежутка нет.
"""

import json
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

RELEASE_NAME = re.compile(r"^(\d{8}-\d{6})(?:-(\d+))?$")
KEEP_RELEASES = 5

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
    return sorted((p for p in site.releases.iterdir() if p.is_dir() and RELEASE_NAME.match(p.name)), key=_order)


def _order(path: Path) -> tuple[str, int]:
    """Время, затем номер сборки за ту же секунду. Не по строке: «-10» встало бы раньше «-2»."""
    match = RELEASE_NAME.match(path.name)
    assert match is not None  # releases() отбирает только такие имена
    return match.group(1), int(match.group(2) or 0)


def current_release(site: SiteDirs) -> Path | None:
    """На какой релиз указывает public_html; None - ссылки еще нет."""
    if not site.public.is_symlink():
        return None
    target = (site.public.parent / os.readlink(site.public)).resolve()
    return target if target.is_dir() else None


def _new_release_dir(site: SiteDirs, now: int, settings: Settings) -> Path:
    """Имя - местное время; за ту же секунду - номер больше всех занятых, даже если младшие
    уже вычищены: иначе новый релиз получил бы освободившееся «старое» имя."""
    base = datetime.fromtimestamp(now, settings.tz).strftime("%Y%m%d-%H%M%S")
    taken = [n for stamp, n in map(_order, releases(site)) if stamp == base]
    n = max(taken) + 1 if taken else 0
    path = site.releases / (f"{base}-{n}" if n else base)
    while path.exists():  # чужой файл с таким именем
        n += 1
        path = site.releases / f"{base}-{n}"
    return path


def _count_pages(release: Path) -> int:
    return sum(1 for _ in release.rglob("index.html"))


def news_slugs(news_json: Path) -> list[str]:
    """Адреса новостей из news.json: у каждой должна быть своя страница в релизе.

    Raises:
        ReleaseError: news.json не читается.
    """
    try:
        data = json.loads(news_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"{news_json} не читается: {exc}") from None
    posts = data.get("posts") if isinstance(data, dict) else None
    return [str(p["slug"]) for p in posts or [] if isinstance(p, dict) and p.get("slug")]


def check_release(release: Path, site: SiteDirs, slugs: list[str]) -> int:
    """Проверки целостности до переключения. Возвращает число страниц.

    Вместо сравнения с прошлым релизом («страниц стало резко меньше») - проверка, что у
    каждой новости из news.json есть страница: с 2026-10-26 новости уходят с сайта по
    сроку хранения, и меньше страниц - это норма, а не поломка.

    Raises:
        ReleaseError: чего-то нет.
    """
    if not (release / "index.html").is_file():
        raise ReleaseError("в релизе нет index.html")
    if not (release / "sitemap-index.xml").is_file() and not (release / "sitemap-0.xml").is_file():
        raise ReleaseError("в релизе нет sitemap")
    media = release / "media"
    if not media.is_symlink() or media.resolve() != site.media.resolve():
        raise ReleaseError("в релизе нет ссылки media на каталог картинок")
    missing = [slug for slug in slugs if not (release / "news" / slug / "index.html").is_file()]
    if missing:
        raise ReleaseError(f"в релизе нет страниц у {len(missing)} новостей из news.json, например {missing[0]}")
    return _count_pages(release)


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
        # На сервере сборка содержимое только проверяет, файлы клона не правит.
        "CONTENT_CHECK_ONLY": "1",
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


def build_release(settings: Settings, now: int, command: Sequence[str] | None = None, *, switch: bool = True) -> Path:
    """Собрать, проверить, переключить, почистить. Возвращает новый релиз.

    switch=False - пробная сборка (deploy.sh): релиз собран и проверен, но public_html не
    тронут; включить его можно потом командой rollback --to. Так можно собрать новый сайт,
    пока public_html еще обычный каталог старого сайта.

    При любой ошибке созданный этим запуском каталог удаляется, public_html не трогается,
    исключение уходит наружу (воркер оставит флаг «сайт устарел»).
    """
    site = settings.site
    if not settings.data.news_json.is_file():
        raise ReleaseError(f"нет {settings.data.news_json}: сначала python -m pipeline export")
    site.releases.mkdir(parents=True, exist_ok=True)
    site.media.mkdir(parents=True, exist_ok=True)
    if switch:
        ensure_switchable(site)  # до долгой сборки, а не после
    slugs = news_slugs(settings.data.news_json)
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
        pages = check_release(release, site, slugs)
    except BaseException:
        if release.exists():
            shutil.rmtree(release)
        raise
    if switch:
        switch_to(site, release)
    removed = cleanup(site)
    log.info(
        "релиз %s: страниц %s; public_html %s; удалены старые: %s",
        release.name,
        pages,
        "переключен" if switch else "не тронут",
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
        resolved = [p.resolve() for p in found]
        if current is None:
            older = found
        elif current in resolved:
            older = found[: resolved.index(current)]
        else:
            raise ReleaseError(f"public_html указывает не на релиз из releases/ ({current}); укажите --to")
        if not older:
            raise ReleaseError("нет более раннего релиза для отката")
        target = older[-1]
    switch_to(site, target)
    return target
