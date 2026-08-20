from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

_PDF_URL = re.compile(rb"https?://[^\s<>\[\](){}\x00-\x20]+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ExtractedLink:
    url: str
    anchor: str | None
    context: str | None
    rel_flags: tuple[str, ...]
    semantic_location: str
    editorial: bool


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[ExtractedLink] = []
        self.title: str | None = None
        self._stack: list[str] = []
        self._href: str | None = None
        self._rel: tuple[str, ...] = ()
        self._anchor_text: list[str] = []
        self._recent_text: list[str] = []
        self._in_title = False
        self._title_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        self._stack.append(lowered)
        if lowered == "title":
            self._in_title = True
        if lowered != "a":
            return
        values = {key.lower(): value for key, value in attrs}
        self._href = values.get("href")
        self._rel = tuple(sorted((values.get("rel") or "").lower().split()))
        self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._in_title = False
            title = " ".join(" ".join(self._title_text).split())
            self.title = title[:500] if title else None
        if lowered == "a" and self._href:
            absolute = urljoin(self.base_url, self._href)
            anchor = " ".join(" ".join(self._anchor_text).split())[:500] or None
            context = " ".join(self._recent_text[-4:])[-1000:] or None
            semantic = next(
                (
                    item
                    for item in reversed(self._stack)
                    if item in {"article", "section", "main", "nav", "footer", "header", "aside"}
                ),
                "body",
            )
            editorial = semantic not in {"nav", "footer", "header"} and bool(anchor)
            self.links.append(
                ExtractedLink(
                    url=absolute,
                    anchor=anchor,
                    context=context,
                    rel_flags=self._rel,
                    semantic_location=semantic,
                    editorial=editorial,
                )
            )
            self._href = None
            self._rel = ()
            self._anchor_text = []
        if lowered in self._stack:
            reverse_index = self._stack[::-1].index(lowered)
            del self._stack[len(self._stack) - reverse_index - 1]

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self._title_text.append(cleaned)
        if self._href is not None:
            self._anchor_text.append(cleaned)
        self._recent_text.append(cleaned)
        if len(self._recent_text) > 12:
            self._recent_text.pop(0)


def parse_html(content: bytes, base_url: str) -> tuple[str | None, tuple[ExtractedLink, ...]]:
    parser = _LinkParser(base_url)
    parser.feed(content.decode("utf-8", errors="replace"))
    return parser.title, tuple(parser.links)


def parse_pdf_urls(content: bytes) -> tuple[ExtractedLink, ...]:
    seen: set[str] = set()
    links: list[ExtractedLink] = []
    for raw in _PDF_URL.findall(content):
        url = raw.rstrip(b".,;:'\"").decode("utf-8", errors="ignore")
        if not url or url in seen:
            continue
        seen.add(url)
        links.append(
            ExtractedLink(
                url=url,
                anchor=None,
                context="URL extracted from a bounded PDF document",
                rel_flags=(),
                semantic_location="document",
                editorial=True,
            )
        )
    return tuple(links)
