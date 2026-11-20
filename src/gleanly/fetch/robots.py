"""robots.txt handling following RFC 9309."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

import httpx
from protego import Protego

from gleanly.fetch.http import http_get, origin_of

# Crawlers whose purpose is (mainly) collecting AI training data. If robots.txt blocks
# these but allows generic crawlers, the site is signalling an AI opt-out.
AI_TRAINING_CRAWLERS: tuple[str, ...] = (
    "GPTBot",
    "ClaudeBot",
    "anthropic-ai",
    "CCBot",
    "Google-Extended",
    "Applebot-Extended",
    "Bytespider",
    "meta-externalagent",
    "PerplexityBot",
    "cohere-ai",
)
_GENERIC_PROBE = "generic-crawler-probe"


@dataclass(frozen=True)
class RobotsVerdict:
    allowed: bool | None
    status: str
    detail: str
    crawl_delay: float | None = None
    ai_crawlers_blocked: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RobotsFile:
    mode: Literal["parsed", "allow_all", "disallow_all"]
    status: str
    detail: str
    parser: Protego | None = None


class RobotsCache:
    """Fetches and caches robots.txt once per origin."""

    def __init__(self, client: httpx.AsyncClient, *, token: str) -> None:
        self._client = client
        self._token = token
        self._files: dict[str, _RobotsFile] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _get(self, origin: str) -> _RobotsFile:
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            cached = self._files.get(origin)
            if cached is not None:
                return cached
            robots_url = f"{origin}/robots.txt"
            try:
                resp = await http_get(self._client, robots_url, max_bytes=500_000)
            except httpx.HTTPError as exc:
                rf = _RobotsFile(
                    "disallow_all",
                    "unreachable",
                    f"robots.txt unreachable ({type(exc).__name__}); RFC 9309 says to assume "
                    "complete disallow",
                )
            else:
                s = resp.status_code
                if 200 <= s < 300:
                    rf = _RobotsFile(
                        "parsed", "fetched", "robots.txt fetched", Protego.parse(resp.text())
                    )
                elif 400 <= s < 500:
                    rf = _RobotsFile(
                        "allow_all", "missing", f"robots.txt returned HTTP {s}: no restrictions"
                    )
                else:
                    rf = _RobotsFile(
                        "disallow_all",
                        "server-error",
                        f"robots.txt returned HTTP {s}; RFC 9309 says to assume complete disallow",
                    )
            self._files[origin] = rf
            return rf

    async def check(self, url: str) -> RobotsVerdict:
        rf = await self._get(origin_of(url))
        if rf.mode == "allow_all":
            return RobotsVerdict(True, rf.status, rf.detail)
        if rf.mode == "disallow_all" or rf.parser is None:
            return RobotsVerdict(False, rf.status, rf.detail)
        parser = rf.parser
        allowed = bool(parser.can_fetch(url, self._token))
        delay = parser.crawl_delay(self._token)
        blocked: tuple[str, ...] = ()
        if parser.can_fetch(url, _GENERIC_PROBE):
            blocked = tuple(b for b in AI_TRAINING_CRAWLERS if not parser.can_fetch(url, b))
        detail = "allowed by robots.txt" if allowed else "disallowed by robots.txt"
        return RobotsVerdict(
            allowed,
            rf.status,
            detail,
            crawl_delay=float(delay) if delay is not None else None,
            ai_crawlers_blocked=blocked,
        )
