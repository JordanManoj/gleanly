"""Search backends: thin adapters over search engines' official APIs.

Only official, documented APIs are used (no scraping of search result pages), with the
library's honest User-Agent. Each backend returns plain hits; fetching, cleaning,
ranking and cross-checking happen in ``gleanly.search``.

- ``wikipedia``: the MediaWiki search API. No key needed.
- ``brave``: the Brave Search API. Needs an API key (``BRAVE_API_KEY``).
- ``searxng``: a SearXNG instance you run or are allowed to use, with the JSON output
  format enabled in its settings (``SEARXNG_URL``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from html import unescape
from typing import Protocol
from urllib.parse import quote

import httpx

from gleanly.errors import AcquisitionError

_TAG = re.compile(r"<[^>]+>")


class SearchBackendError(AcquisitionError):
    """A backend could not answer (no key, HTTP error, bad response)."""


@dataclass
class RawHit:
    url: str
    title: str = ""
    snippet: str = ""


class Backend(Protocol):
    name: str

    async def search(self, client: httpx.AsyncClient, query: str, count: int) -> list[RawHit]: ...


def _clean(text: str | None) -> str:
    return " ".join(unescape(_TAG.sub("", text or "")).split())


async def _get_json(
    client: httpx.AsyncClient, url: str, *, params: dict[str, str], headers: dict[str, str]
) -> object:
    try:
        resp = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise SearchBackendError(f"{url}: {type(exc).__name__}: {exc}") from exc
    if resp.status_code != 200:
        raise SearchBackendError(f"{url}: HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise SearchBackendError(f"{url}: response is not JSON") from exc


@dataclass
class Wikipedia:
    """MediaWiki search API (https://www.mediawiki.org/wiki/API:Search)."""

    lang: str = "en"
    name: str = field(default="wikipedia", init=False)

    async def search(self, client: httpx.AsyncClient, query: str, count: int) -> list[RawHit]:
        base = f"https://{self.lang}.wikipedia.org"
        data = await _get_json(
            client,
            f"{base}/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": str(min(count, 50)),
                "format": "json",
                "formatversion": "2",
            },
            headers={"Accept": "application/json"},
        )
        items = (data.get("query") or {}).get("search") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SearchBackendError("wikipedia: unexpected response shape")
        hits = []
        for it in items:
            title = str(it.get("title") or "")
            if not title:
                continue
            url = f"{base}/wiki/{quote(title.replace(' ', '_'), safe='()_,')}"
            hits.append(RawHit(url, title, _clean(it.get("snippet"))))
        return hits


@dataclass
class Brave:
    """Brave Search API (https://brave.com/search/api/). Key from ``BRAVE_API_KEY``."""

    api_key: str | None = None
    name: str = field(default="brave", init=False)

    async def search(self, client: httpx.AsyncClient, query: str, count: int) -> list[RawHit]:
        key = self.api_key or os.environ.get("BRAVE_API_KEY")
        if not key:
            raise SearchBackendError(
                "brave: no API key. Get one at https://brave.com/search/api/ and set the "
                "BRAVE_API_KEY environment variable."
            )
        data = await _get_json(
            client,
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": str(min(count, 20))},
            headers={"Accept": "application/json", "X-Subscription-Token": key},
        )
        web = data.get("web") if isinstance(data, dict) else None
        items = web.get("results") if isinstance(web, dict) else None
        if not isinstance(items, list):
            return []  # no web results for this query
        return [
            RawHit(str(it["url"]), _clean(it.get("title")), _clean(it.get("description")))
            for it in items
            if isinstance(it, dict) and it.get("url")
        ]


@dataclass
class SearXNG:
    """A SearXNG instance's JSON API. URL from ``SEARXNG_URL``.

    The instance must allow ``format=json`` (``search.formats`` in its settings.yml).
    """

    base_url: str | None = None
    name: str = field(default="searxng", init=False)

    async def search(self, client: httpx.AsyncClient, query: str, count: int) -> list[RawHit]:
        base = (self.base_url or os.environ.get("SEARXNG_URL") or "").rstrip("/")
        if not base:
            raise SearchBackendError(
                "searxng: no instance URL. Set SEARXNG_URL to your instance, e.g. "
                "http://localhost:8888"
            )
        data = await _get_json(
            client,
            f"{base}/search",
            params={"q": query, "format": "json"},
            headers={"Accept": "application/json"},
        )
        items = data.get("results") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SearchBackendError("searxng: unexpected response (is format=json enabled?)")
        return [
            RawHit(str(it["url"]), _clean(it.get("title")), _clean(it.get("content")))
            for it in items[:count]
            if isinstance(it, dict) and it.get("url")
        ]


BACKENDS = {"wikipedia": Wikipedia, "brave": Brave, "searxng": SearXNG}


def default_backends() -> list[Backend]:
    """Every backend that can run here: Wikipedia always, others when configured."""
    out: list[Backend] = [Wikipedia()]
    if os.environ.get("BRAVE_API_KEY"):
        out.append(Brave())
    if os.environ.get("SEARXNG_URL"):
        out.append(SearXNG())
    return out


__all__ = [
    "BACKENDS",
    "Backend",
    "Brave",
    "RawHit",
    "SearXNG",
    "SearchBackendError",
    "Wikipedia",
    "default_backends",
]
