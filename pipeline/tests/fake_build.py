"""Поддельная сборка сайта для тестов: пишет релиз в ASTRO_OUT_DIR или имитирует сбой.

    python fake_build.py <режим> <страниц>
режимы: ok, no-index, no-sitemap, fail, slow, env (записать окружение в env.txt)
"""

import os
import sys
import time
from pathlib import Path

mode, pages = sys.argv[1], int(sys.argv[2])
out = Path(os.environ["ASTRO_OUT_DIR"])
if mode == "fail":
    print("сборка упала: синтаксическая ошибка", file=sys.stderr)
    sys.exit(1)
if mode == "slow":
    time.sleep(30)
out.mkdir(parents=True)
if mode != "no-index":
    (out / "index.html").write_text("<html>главная</html>", encoding="utf-8")
if mode != "no-sitemap":
    (out / "sitemap-index.xml").write_text("<sitemapindex/>", encoding="utf-8")
for i in range(pages - 1):
    page = out / "news" / f"p{i}"
    page.mkdir(parents=True)
    (page / "index.html").write_text(f"<html>{i}</html>", encoding="utf-8")
if mode == "env":
    (out / "env.txt").write_text("\n".join(f"{k}={v}" for k, v in sorted(os.environ.items())), encoding="utf-8")
