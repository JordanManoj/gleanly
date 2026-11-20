from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from gleanly.config import LoadOptions

_HEADER_CHARSET = re.compile(r"charset=[\"']?([\w.:-]+)", re.I)
_META_CHARSET = re.compile(rb"<meta[^>]+charset=[\"']?([\w.:-]+)", re.I)


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    truncated: bool = False
    elapsed_ms: float = 0.0

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    def text(self) -> str:
        return decode_bytes(self.content, self.headers.get("content-type"))


def decode_bytes(content: bytes, content_type_header: str | None = None) -> str:
    """Decode using the header charset, then a <meta charset>, then UTF-8."""
    candidates: list[str] = []
    if content_type_header and (m := _HEADER_CHARSET.search(content_type_header)):
        candidates.append(m.group(1))
    if m2 := _META_CHARSET.search(content[:4096]):
        candidates.append(m2.group(1).decode("ascii", "ignore"))
    candidates.append("utf-8")
    for enc in candidates:
        try:
            return content.decode(enc).lstrip("﻿")
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace").lstrip("﻿")


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def build_client(options: LoadOptions) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={
            "User-Agent": options.user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
        timeout=options.timeout,
        follow_redirects=True,
        max_redirects=options.max_redirects,
    )


async def http_get(client: httpx.AsyncClient, url: str, *, max_bytes: int) -> HttpResponse:
    """GET ``url``, reading at most ``max_bytes`` of the body."""
    t0 = time.perf_counter()
    async with client.stream("GET", url) as resp:
        chunks: list[bytes] = []
        size = 0
        truncated = False
        async for chunk in resp.aiter_bytes():
            remaining = max_bytes - size
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                truncated = True
                break
            chunks.append(chunk)
            size += len(chunk)
        return HttpResponse(
            url=str(resp.url),
            status_code=resp.status_code,
            headers={k.lower(): v for k, v in resp.headers.items()},
            content=b"".join(chunks),
            truncated=truncated,
            elapsed_ms=round((time.perf_counter() - t0) * 1000, 1),
        )


def explain_status(status: int, headers: dict[str, str]) -> str:
    """A human-readable reason for a non-2xx response."""
    if status in (401, 407):
        return f"HTTP {status}: the page requires authentication."
    if status == 403:
        return (
            "HTTP 403: the server refused access. The site may block automated clients; "
            "this library does not try to evade blocks. Archive/RSS/API fallbacks are planned."
        )
    if status in (404, 410):
        return f"HTTP {status}: the page was not found."
    if status == 429:
        retry = headers.get("retry-after")
        suffix = f" Retry-After: {retry}." if retry else ""
        return f"HTTP 429: rate limited by the server.{suffix}"
    if status == 451:
        return "HTTP 451: unavailable for legal reasons."
    if status >= 500:
        return f"HTTP {status}: server error; try again later."
    return f"HTTP {status}: unexpected response."
