"""fetch_url helpers for local static site and live HTTPS."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

CAP = 12_000


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.chunks: list[str] = []
        self.links: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title += data
        else:
            self.chunks.append(data)


def parse_html(html: str, base_url: str = "") -> dict[str, Any]:
    p = _TextParser()
    p.feed(html)
    text = re.sub(r"\s+", " ", " ".join(p.chunks)).strip()
    if len(text) > CAP:
        text = text[:CAP]
    links = [urljoin(base_url, h) for h in p.links][:200]
    return {"title": p.title.strip(), "text": text, "links": links}


def fetch_local(url: str, base: str, pages: dict[str, str]) -> dict[str, Any]:
    path = urlparse(url).path or "/"
    if path not in pages:
        return {"title": "404", "text": "Not found", "links": []}
    html = pages[path]
    return parse_html(html, base)


def fetch_live(url: str, client: httpx.Client) -> dict[str, Any]:
    if not url.startswith("https://"):
        return {"title": "error", "text": "https only", "links": []}
    r = client.get(url, follow_redirects=True, timeout=15.0)
    r.raise_for_status()
    return parse_html(r.text, str(r.url))
