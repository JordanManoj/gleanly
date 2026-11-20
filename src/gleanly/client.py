"""Orchestrates the fetch ladder, extraction, quality and compliance into a Document."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit

import httpx
from lxml.html import HtmlElement

from gleanly.clean.blocks import rescue
from gleanly.clean.comments import with_comments
from gleanly.clean.html import Extraction, RawBlock, extract_html, markdown_to_plain, parse_html
from gleanly.clean.metadata import extract_metadata, iter_json_ld
from gleanly.compliance import tdmrep
from gleanly.compliance.assess import assess, detect_noai
from gleanly.compliance.license import detect_license
from gleanly.compliance.pii import detect_pii
from gleanly.config import LoadOptions
from gleanly.errors import (
    BrowserUnavailable,
    FetchError,
    RobotsDisallowed,
    UnsupportedSourceError,
)
from gleanly.fetch import router
from gleanly.fetch.browser import render_page
from gleanly.fetch.embedded import extract_embedded
from gleanly.fetch.http import build_client, explain_status, http_get, origin_of
from gleanly.fetch.ratelimit import DomainRateLimiter
from gleanly.fetch.robots import RobotsCache, RobotsVerdict
from gleanly.models import (
    Block,
    BlockType,
    Document,
    FetchStep,
    FetchTrace,
    Metadata,
    Provenance,
)
from gleanly.quality import compute_quality
from gleanly.quality.crosscheck import cross_check

Source = str | os.PathLike[str]
_HTML_TYPES = {"text/html", "application/xhtml+xml", ""}
_TEXT_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
_BARE_DOMAIN = re.compile(r"^[\w-]+(\.[\w-]+)+(/.*)?$")


def assemble(raw_blocks: list[RawBlock], source: str) -> tuple[str, list[Block]]:
    """Join blocks into Markdown and record each block's character span."""
    parts: list[str] = []
    blocks: list[Block] = []
    pos = 0
    for rb in raw_blocks:
        if parts:
            pos += 2  # "\n\n" separator
        start = pos
        parts.append(rb.text)
        pos += len(rb.text)
        kind = rb.kind if rb.kind in ("html", "embedded", "text") else "html"
        blocks.append(
            Block(
                text=rb.text,
                type=rb.type,
                level=rb.level,
                support=rb.support,
                role="comment" if rb.role == "comment" else "main",
                provenance=Provenance(
                    source=source,
                    kind=kind,  # type: ignore[arg-type]
                    dom_path=rb.dom_path,
                    char_start=start,
                    char_end=pos,
                ),
            )
        )
    return "\n\n".join(parts), blocks


def _text_blocks(text: str, markdown: bool) -> list[RawBlock]:
    out: list[RawBlock] = []
    for i, chunk in enumerate(re.split(r"\n\s*\n", text.replace("\r\n", "\n"))):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r"^(#{1,6})\s+\S", chunk) if markdown else None
        if m and "\n" not in chunk:
            out.append(RawBlock(BlockType.HEADING, chunk, f"chunk[{i}]", len(m.group(1)), "text"))
        else:
            out.append(RawBlock(BlockType.PARAGRAPH, chunk, f"chunk[{i}]", kind="text"))
    return out


async def _none() -> None:
    return None


class Client:
    """Reusable loader. Shares connections, robots.txt cache and per-host rate limits.

    >>> async with Client() as client:
    ...     doc = await client.aload("https://example.com")
    """

    def __init__(
        self,
        options: LoadOptions | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        **overrides: Any,
    ) -> None:
        opts = options or LoadOptions()
        if overrides:
            opts = LoadOptions(**{**opts.model_dump(), **overrides})
        self.options = opts
        self._owns_http = http_client is None
        self._http = http_client or build_client(opts)
        self._robots = RobotsCache(self._http, token=opts.robots_token)
        self._tdm = tdmrep.TdmRepCache(self._http)
        self._limiter = DomainRateLimiter(opts.min_delay)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> Client:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ----------------------------------------------------------------- entry
    async def aload(self, source: Source) -> Document:
        if isinstance(source, os.PathLike):
            return self._load_file(Path(source), str(source))
        src = source.strip()
        if src.lower().startswith(("http://", "https://")):
            return await self._load_url(src, src)
        path = Path(src).expanduser()
        if path.exists():
            return self._load_file(path, src)
        if _BARE_DOMAIN.match(src):
            return await self._load_url("https://" + src, src)
        raise UnsupportedSourceError(f"Not a URL or an existing file: {source!r}")

    # ------------------------------------------------------------------ file
    def _load_file(self, path: Path, source: str) -> Document:
        if not path.is_file():
            raise UnsupportedSourceError(f"Not a file: {path}")
        uri = path.resolve().as_uri()
        suffix = path.suffix.lower()
        data = path.read_bytes()
        trace = FetchTrace(
            steps=[FetchStep(rung="file", url=uri, ok=True, detail=f"{len(data)} bytes")],
            final_url=uri,
            final_rung="file",
        )
        if suffix in (".html", ".htm", ".xhtml"):
            from gleanly.fetch.http import decode_bytes

            root = parse_html(decode_bytes(data))
            extraction = extract_html(
                root, None, method="file", include_comments=self.options.include_comments
            )
            js_suspect = router.looks_js_rendered(root, extraction)
            extraction = self._try_embedded(root, uri, extraction, trace, js_suspect)
            extraction = rescue(extraction, root) or extraction
            if self.options.include_comments and extraction.method == "embedded":
                extraction = with_comments(extraction, root)
            json_ld = iter_json_ld(root)
            metadata = extract_metadata(root, url=None, content_type="text/html", json_ld=json_ld)
            license_info = detect_license(root, json_ld, None)
            noai = detect_noai({}, root)
            tdm_signals = [s for s in (tdmrep.from_html(root),) if s]
        elif suffix in (".txt", ".md", ".markdown", ".text"):
            text = data.decode("utf-8", errors="replace").lstrip("﻿")
            extraction = Extraction(_text_blocks(text, suffix != ".txt"), "file")
            metadata = Metadata(content_type="text/markdown" if suffix != ".txt" else "text/plain")
            license_info, noai, tdm_signals = None, [], []
            root = None
        else:
            raise UnsupportedSourceError(
                f"Unsupported file type {suffix or '(none)'}: PDFs and images arrive in Phase 2."
            )
        return self._build(
            source=source,
            url=uri,
            extraction=extraction,
            metadata=metadata,
            trace=trace,
            raw_size=len(data),
            robots=None,
            tdm_signals=tdm_signals,
            noai=noai,
            license_info=license_info,
            check_root=root,
            local=True,
        )

    # ------------------------------------------------------------------- web
    async def _check_origin(
        self, url: str, trace: FetchTrace
    ) -> tuple[RobotsVerdict, tdmrep.TdmSignal | None]:
        o = self.options
        robots, tdm_wk = await asyncio.gather(
            self._robots.check(url),
            self._tdm.lookup(url) if o.check_tdmrep else _none(),
        )
        trace.steps.append(
            FetchStep(
                rung="robots",
                url=f"{origin_of(url)}/robots.txt",
                ok=robots.allowed is not False,
                detail=robots.detail,
            )
        )
        if o.check_tdmrep:
            trace.steps.append(
                FetchStep(
                    rung="tdmrep",
                    url=f"{origin_of(url)}/.well-known/tdmrep.json",
                    ok=True,
                    detail=tdm_wk.describe() if tdm_wk else "no matching TDMRep rule",
                )
            )
        if robots.allowed is False and o.respect_robots:
            reason = (
                f"robots.txt does not allow '{o.robots_token}' to fetch {url} "
                f"({robots.detail}). Pass respect_robots=False only if you have permission."
            )
            trace.failure_reason = reason
            raise RobotsDisallowed(reason, url=url, trace=trace)
        return robots, tdm_wk

    async def _load_url(self, url: str, source: str) -> Document:
        o = self.options
        trace = FetchTrace()
        robots, tdm_wk = await self._check_origin(url, trace)
        host = urlsplit(url).netloc.lower()

        # Rung 1: plain HTTP
        await self._limiter.wait(host, robots.crawl_delay)
        try:
            resp = await http_get(self._http, url, max_bytes=o.max_bytes)
        except httpx.TimeoutException as exc:
            raise self._fail(trace, url, f"Timed out after {o.timeout}s.") from exc
        except httpx.TooManyRedirects as exc:
            raise self._fail(trace, url, "Too many redirects.") from exc
        except httpx.HTTPError as exc:
            raise self._fail(trace, url, f"Network error: {type(exc).__name__}: {exc}") from exc

        ok = 200 <= resp.status_code < 300
        trace.steps.append(
            FetchStep(
                rung="http",
                url=resp.url,
                ok=ok,
                status_code=resp.status_code,
                duration_ms=resp.elapsed_ms,
                detail=f"{resp.content_type or 'unknown type'}, {len(resp.content)} bytes",
            )
        )
        if not ok:
            reason = explain_status(resp.status_code, resp.headers)
            trace.failure_reason = reason
            raise FetchError(reason, url=url, trace=trace)
        if origin_of(resp.url) != origin_of(url):  # redirected to another site
            robots, tdm_wk = await self._check_origin(resp.url, trace)

        ctype = resp.content_type
        if ctype == "application/pdf" or ctype.startswith("image/"):
            raise UnsupportedSourceError(f"{ctype} content arrives in Phase 2 (PDF/OCR).")
        text = resp.text()
        tdm_signals = [s for s in (tdm_wk, tdmrep.from_headers(resp.headers)) if s]

        if ctype in _TEXT_TYPES or (ctype not in _HTML_TYPES and ctype.startswith("text/")):
            extraction = Extraction(_text_blocks(text, "markdown" in ctype), "http")
            trace.final_url, trace.final_rung = resp.url, "http"
            return self._build(
                source=source,
                url=resp.url,
                extraction=extraction,
                metadata=Metadata(content_type=ctype, status_code=resp.status_code),
                trace=trace,
                raw_size=len(resp.content),
                robots=robots,
                tdm_signals=tdm_signals,
                noai=detect_noai(resp.headers, None),
                license_info=None,
                truncated=resp.truncated,
            )
        if ctype not in _HTML_TYPES:
            raise UnsupportedSourceError(f"Unsupported content type {ctype!r} at {resp.url}.")

        root = parse_html(text)
        extraction = extract_html(
            root, resp.url, method="http", include_comments=o.include_comments
        )
        js_suspect = router.looks_js_rendered(root, extraction)

        # Rung 2: embedded data
        extraction = self._try_embedded(root, resp.url, extraction, trace, js_suspect)
        extraction = rescue(extraction, root) or extraction
        if o.include_comments and extraction.method == "embedded":
            extraction = with_comments(extraction, root)

        # Rung 3: browser
        final_root = root
        want_browser = o.browser == "always" or (
            o.browser == "auto" and router.is_poor(extraction) and js_suspect
        )
        if want_browser:
            await self._limiter.wait(host, robots.crawl_delay)
            try:
                page = await render_page(resp.url, user_agent=o.user_agent, timeout=o.timeout)
            except BrowserUnavailable as exc:
                trace.steps.append(
                    FetchStep(rung="browser", url=resp.url, ok=False, detail=str(exc))
                )
            except Exception as exc:  # Playwright navigation errors, timeouts, ...
                trace.steps.append(
                    FetchStep(
                        rung="browser",
                        url=resp.url,
                        ok=False,
                        detail=f"render failed: {type(exc).__name__}: {exc}",
                    )
                )
            else:
                r_root = parse_html(page.html)
                rendered = extract_html(
                    r_root, page.url, method="browser", include_comments=o.include_comments
                )
                use = o.browser == "always" or router.better(rendered, extraction)
                trace.steps.append(
                    FetchStep(
                        rung="browser",
                        url=page.url,
                        ok=use,
                        status_code=page.status_code,
                        detail=f"{rendered.word_count} words after rendering",
                    )
                )
                if use:
                    extraction, final_root = rendered, r_root
                    js_suspect = False

        trace.final_url, trace.final_rung = resp.url, extraction.method
        json_ld = iter_json_ld(final_root)
        metadata = extract_metadata(
            final_root,
            url=resp.url,
            status_code=resp.status_code,
            content_type=ctype or None,
            json_ld=json_ld,
        )
        html_tdm = tdmrep.from_html(final_root)
        if html_tdm:
            tdm_signals.append(html_tdm)
        return self._build(
            source=source,
            url=resp.url,
            extraction=extraction,
            metadata=metadata,
            trace=trace,
            raw_size=len(resp.content),
            robots=robots,
            tdm_signals=tdm_signals,
            noai=detect_noai(resp.headers, final_root),
            license_info=detect_license(final_root, json_ld, resp.url),
            truncated=resp.truncated,
            js_suspect=js_suspect,
            check_root=final_root,
        )

    @staticmethod
    def _try_embedded(
        root: HtmlElement,
        url: str,
        extraction: Extraction,
        trace: FetchTrace,
        js_suspect: bool,
    ) -> Extraction:
        """Rung 2: prefer data embedded in the page when the visible text is poor."""
        if not (router.is_poor(extraction) or js_suspect):
            return extraction
        base = url if url.startswith(("http://", "https://")) else None
        embedded = extract_embedded(root, base)
        use = router.better(embedded, extraction)
        trace.steps.append(
            FetchStep(
                rung="embedded",
                url=url,
                ok=use,
                detail=(
                    f"{embedded.word_count} words from embedded data"
                    if embedded
                    else "no JSON-LD article body or framework state found"
                ),
            )
        )
        if use and embedded is not None:
            trace.final_rung = "embedded"
            return embedded
        return extraction

    @staticmethod
    def _fail(trace: FetchTrace, url: str, reason: str) -> FetchError:
        trace.steps.append(FetchStep(rung="http", url=url, ok=False, detail=reason))
        trace.failure_reason = reason
        return FetchError(reason, url=url, trace=trace)

    def _build(
        self,
        *,
        source: str,
        url: str,
        extraction: Extraction,
        metadata: Metadata,
        trace: FetchTrace,
        raw_size: int,
        robots: RobotsVerdict | None,
        tdm_signals: list[tdmrep.TdmSignal],
        noai: list[str],
        license_info: Any,
        check_root: HtmlElement | None = None,
        local: bool = False,
        truncated: bool = False,
        js_suspect: bool = False,
    ) -> Document:
        check = cross_check(extraction, check_root)
        for raw, support in zip(extraction.blocks, check.block_support, strict=True):
            raw.support = support
        markdown, blocks = assemble(extraction.blocks, url)
        plain = " ".join(markdown_to_plain(b.text) for b in extraction.blocks)
        compliance = assess(
            robots=robots,
            respect_robots=self.options.respect_robots,
            tdm_signals=tdm_signals,
            noai_evidence=noai,
            license_info=license_info,
            pii_types=detect_pii(plain),
            local=local,
        )
        quality = compute_quality(
            extraction,
            raw_size=raw_size,
            status_code=metadata.status_code,
            language=metadata.language,
            truncated=truncated,
            js_suspect=js_suspect,
            extraction_confidence=check.confidence,
            extraction_support=check.support,
            extraction_coverage=check.coverage,
        )
        return Document(
            source=source,
            url=url,
            markdown=markdown,
            blocks=blocks,
            metadata=metadata,
            quality=quality,
            compliance=compliance,
            fetch_trace=trace,
        )
