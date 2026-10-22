"""Склейка стадий: parse -> media -> export."""

from pathlib import Path

import httpx

from pipeline.export import export_post
from pipeline.media.photos import download_photo
from pipeline.parse import parse_raw
from pipeline.settings import DataDirs


def process(data: DataDirs, media_dir: Path, http: httpx.Client) -> int:
    """parse + media + export по всем сырым событиям. Идемпотентно: готовое пропускается."""
    posts = parse_raw(data.raw)
    for post in posts:
        for photo in post.photos:
            download_photo(http, photo, media_dir)
        export_post(post, media_dir, data.content)
    return len(posts)
