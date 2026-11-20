from __future__ import annotations

import time

import httpx
import pytest
import respx

from gleanly.fetch.http import decode_bytes, explain_status, http_get
from gleanly.fetch.ratelimit import DomainRateLimiter
from gleanly.fetch.robots import RobotsCache

ORIGIN = "https://site.example"
ROBOTS = f"{ORIGIN}/robots.txt"

# ---------------------------------------------------------------- robots.txt


async def _check(mock_http: respx.MockRouter, url: str, **response: object):
    mock_http.get(ROBOTS).mock(return_value=httpx.Response(**response))  # type: ignore[arg-type]
    async with httpx.AsyncClient() as http:
        return await RobotsCache(http, token="gleanly").check(url)


async def test_robots_allow_and_disallow(mock_http: respx.MockRouter) -> None:
    text = "User-agent: *\nDisallow: /private/\nCrawl-delay: 3\n"
    ok = await _check(mock_http, f"{ORIGIN}/public", status_code=200, text=text)
    assert ok.allowed is True
    assert ok.crawl_delay == 3.0
    no = await _check(mock_http, f"{ORIGIN}/private/x", status_code=200, text=text)
    assert no.allowed is False


async def test_robots_specific_token_group(mock_http: respx.MockRouter) -> None:
    text = "User-agent: gleanly\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    verdict = await _check(mock_http, f"{ORIGIN}/a", status_code=200, text=text)
    assert verdict.allowed is False


async def test_robots_detects_ai_opt_out(mock_http: respx.MockRouter) -> None:
    text = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: CCBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"  # noqa: E501
    verdict = await _check(mock_http, f"{ORIGIN}/a", status_code=200, text=text)
    assert verdict.allowed is True
    assert verdict.ai_crawlers_blocked == ("GPTBot", "CCBot")


async def test_robots_missing_means_allow(mock_http: respx.MockRouter) -> None:
    verdict = await _check(mock_http, f"{ORIGIN}/a", status_code=404)
    assert verdict.allowed is True
    assert verdict.status == "missing"


async def test_robots_server_error_means_disallow(mock_http: respx.MockRouter) -> None:
    verdict = await _check(mock_http, f"{ORIGIN}/a", status_code=503)
    assert verdict.allowed is False
    assert "RFC 9309" in verdict.detail


async def test_robots_unreachable_means_disallow(mock_http: respx.MockRouter) -> None:
    mock_http.get(ROBOTS).mock(side_effect=httpx.ConnectError("boom"))
    async with httpx.AsyncClient() as http:
        verdict = await RobotsCache(http, token="gleanly").check(f"{ORIGIN}/a")
    assert verdict.allowed is False
    assert verdict.status == "unreachable"


async def test_robots_is_cached_per_origin(mock_http: respx.MockRouter) -> None:
    route = mock_http.get(ROBOTS).mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as http:
        cache = RobotsCache(http, token="gleanly")
        for path in ("/a", "/b", "/c"):
            await cache.check(ORIGIN + path)
    assert route.call_count == 1


# ---------------------------------------------------------------- http helpers


async def test_http_get_truncates_at_max_bytes(mock_http: respx.MockRouter) -> None:
    mock_http.get(f"{ORIGIN}/big").mock(return_value=httpx.Response(200, content=b"x" * 5000))
    async with httpx.AsyncClient() as http:
        resp = await http_get(http, f"{ORIGIN}/big", max_bytes=1000)
    assert resp.truncated
    assert len(resp.content) == 1000


def test_decode_bytes_charsets() -> None:
    latin = "café".encode("latin-1")
    assert decode_bytes(latin, "text/html; charset=ISO-8859-1") == "café"
    assert decode_bytes(b'<meta charset="iso-8859-1">' + latin).endswith("café")
    assert decode_bytes("﻿hé".encode()) == "hé"
    assert decode_bytes(b"\xff\xfe broken", "text/html; charset=bogus").endswith("broken")


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (401, "authentication"),
        (403, "does not try to evade"),
        (404, "not found"),
        (429, "Retry-After: 30"),
        (451, "legal"),
        (502, "server error"),
        (418, "unexpected"),
    ],
)
def test_explain_status(status: int, needle: str) -> None:
    assert needle in explain_status(status, {"retry-after": "30"})


# ---------------------------------------------------------------- rate limiting


async def test_rate_limiter_spaces_requests_per_host() -> None:
    limiter = DomainRateLimiter(min_delay=0.05)
    assert await limiter.wait("a.example") == 0.0
    t0 = time.monotonic()
    await limiter.wait("a.example")
    assert time.monotonic() - t0 >= 0.04
    assert await limiter.wait("b.example") == 0.0  # other hosts are independent


async def test_rate_limiter_honours_crawl_delay() -> None:
    limiter = DomainRateLimiter(min_delay=0.0)
    await limiter.wait("a.example", crawl_delay=0.05)
    assert await limiter.wait("a.example", crawl_delay=0.05) > 0.0
