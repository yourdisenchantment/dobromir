"""Стадия 2. Читает сырые ответы и раскладывает их по полям. В сеть не ходит."""

from pipeline.parse.model import Link, Photo, Post
from pipeline.parse.posts import parse_post, parse_raw

__all__ = ["Link", "Photo", "Post", "parse_post", "parse_raw"]
