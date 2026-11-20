"""End-to-end tests of the loader with mocked HTTP (no real network)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from gleanly import (
    BrowserUnavailable,
    Client,
    Document,
    FetchError,
    RobotsDisallowed,
    UnsupportedSourceError,
    aload,
    load,
)
from gleanly.config import DEFAULT_USER_AGENT
from gleanly.fetch import browser as browser_mod

from .conftest import FIXTURES, fixture_text

SITE = "https://fieldnotes.example"
PAGE = f"{SITE}/guides/tide-pools"
HTML = "text/html; charset=utf-8"


def _site(
    router: respx.MockRouter,
    *,
    robots: str | None = "User-agent: *\nAllow: /\n",
    tdmrep: object = None,
    ai_txt: str | None = None,
) -> None:
    if robots is None:
        router.get(f"{SITE}/robots.txt").mock(return_value=httpx.Response(404))
    else:
        router.get(f"{SITE}/robots.txt").mock(return_value=httpx.Response(200, text=robots))
    wk = f"{SITE}/.well-known/tdmrep.json"
    if tdmrep is None:
        router.get(wk).mock(return_value=httpx.Response(404))
    else:
        router.get(wk).mock(return_value=httpx.Response(200, json=tdmrep))
    if ai_txt is None:
        router.get(f"{SITE}/ai.txt").mock(return_value=httpx.Response(404))
    else:
        router.get(f"{SITE}/ai.txt").mock(
            return_value=httpx.Response(200, text=ai_txt, headers={"content-type": "text/plain"})
        )


def _page(router: respx.MockRouter, url: str, body: str, **headers: str) -> respx.Route:
    return router.get(url).mock(
        return_value=httpx.Response(200, text=body, headers={"content-type": HTML, **headers})
    )


async def test_load_article(mock_http: respx.MockRouter, client: Client) -> None:
    _site(mock_http)
    route = _page(mock_http, PAGE, fixture_text("article.html"))
    doc = await client.aload(PAGE)

    assert isinstance(doc, Document)
    assert doc.url == PAGE
    assert doc.markdown.startswith("# Understanding Tide Pools")
    assert doc.metadata.title == "Understanding Tide Pools"
    assert doc.metadata.status_code == 200
    assert doc.quality.extraction_method == "http"
    assert doc.quality.score > 0.7
    assert doc.quality.warnings == []
    assert doc.quality.extraction_confidence is not None
    assert doc.quality.extraction_confidence >= 0.9
    assert any(b.support is not None for b in doc.blocks)
    assert doc.compliance.robots_allowed is True
    assert doc.compliance.license == "CC-BY-4.0"
    assert doc.compliance.ai_use == "allowed"
    assert [s.rung for s in doc.fetch_trace.steps] == ["robots", "tdmrep", "ai.txt", "http"]
    assert doc.fetch_trace.final_rung == "http"
    for b in doc.blocks:
        assert doc.markdown[b.provenance.char_start : b.provenance.char_end] == b.text

    # Honest identification on every request.
    ua = route.calls.last.request.headers["user-agent"]
    assert ua == DEFAULT_USER_AGENT
    assert ua.startswith("gleanly/")
    assert "Mozilla" not in ua


async def test_spa_uses_embedded_rung(mock_http: respx.MockRouter, client: Client) -> None:
    _site(mock_http)
    url = f"{SITE}/posts/composting"
    _page(mock_http, url, fixture_text("spa_next.html"))
    doc = await client.aload(url)
    assert doc.quality.extraction_method == "embedded"
    assert doc.fetch_trace.final_rung == "embedded"
    assert "Composting turns kitchen scraps" in doc.markdown
    assert doc.blocks[0].provenance.kind == "embedded"
    embedded_step = next(s for s in doc.fetch_trace.steps if s.rung == "embedded")
    assert embedded_step.ok


async def test_browser_rung_reports_missing_extra(
    mock_http: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unavailable(*_a: object, **_k: object) -> None:
        raise BrowserUnavailable(browser_mod.INSTALL_HINT)

    monkeypatch.setattr("gleanly.client.render_page", unavailable)
    _site(mock_http)
    url = f"{SITE}/app"
    _page(mock_http, url, '<html><body><div id="root"></div></body></html>')
    async with Client(min_delay=0, browser="auto") as c:
        doc = await c.aload(url)
    step = doc.fetch_trace.steps[-1]
    assert step.rung == "browser"
    assert not step.ok
    assert "playwright install chromium" in (step.detail or "")
    assert any("[browser] extra" in w for w in doc.quality.warnings)


async def test_browser_rung_used_when_better(
    mock_http: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = fixture_text("article.html")

    async def fake_render(url: str, **_k: object) -> browser_mod.RenderedPage:
        return browser_mod.RenderedPage(url=url, html=rendered, status_code=200)

    monkeypatch.setattr("gleanly.client.render_page", fake_render)
    _site(mock_http)
    url = f"{SITE}/app"
    _page(mock_http, url, '<html><body><div id="root"></div></body></html>')
    async with Client(min_delay=0) as c:
        doc = await c.aload(url)
    assert doc.quality.extraction_method == "browser"
    assert doc.metadata.title == "Understanding Tide Pools"
    assert doc.fetch_trace.steps[-1].ok


async def test_robots_disallow_raises_with_trace(
    mock_http: respx.MockRouter, client: Client
) -> None:
    _site(mock_http, robots="User-agent: *\nDisallow: /guides/\n")
    page = _page(mock_http, PAGE, "<p>never fetched</p>")
    with pytest.raises(RobotsDisallowed) as info:
        await client.aload(PAGE)
    assert not page.called
    trace = info.value.trace
    assert trace is not None
    assert trace.failure_reason is not None
    assert "respect_robots=False" in trace.failure_reason
    assert trace.steps[0].rung == "robots"
    assert not trace.steps[0].ok


async def test_ignore_robots_marks_disallowed(mock_http: respx.MockRouter) -> None:
    _site(mock_http, robots="User-agent: *\nDisallow: /\n")
    _page(mock_http, PAGE, fixture_text("article.html"))
    async with Client(min_delay=0, browser="never", respect_robots=False) as c:
        doc = await c.aload(PAGE)
    assert doc.compliance.robots_allowed is False
    assert doc.compliance.ai_use == "disallowed"
    assert any("ignored at the caller's request" in e for e in doc.compliance.evidence)


async def test_compliance_signals_from_headers_and_well_known(
    mock_http: respx.MockRouter, client: Client
) -> None:
    _site(mock_http, tdmrep=[{"location": "/guides/*", "tdm-reservation": 1}])
    _page(mock_http, PAGE, fixture_text("article.html"), **{"x-robots-tag": "noai"})
    doc = await client.aload(PAGE)
    c = doc.compliance
    assert c.tdm_reserved is True
    assert c.noai is True
    assert c.ai_use == "disallowed"
    tdm_step = next(s for s in doc.fetch_trace.steps if s.rung == "tdmrep")
    assert "reserved" in (tdm_step.detail or "")


async def test_ai_crawler_opt_out(mock_http: respx.MockRouter, client: Client) -> None:
    _site(mock_http, robots="User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    _page(mock_http, PAGE, fixture_text("article.html"))
    doc = await client.aload(PAGE)
    assert doc.compliance.ai_crawlers_blocked == ["GPTBot"]
    assert doc.compliance.ai_use == "disallowed"


@pytest.mark.parametrize(("status", "needle"), [(403, "refused access"), (404, "not found")])
async def test_http_errors_are_explained(
    mock_http: respx.MockRouter, client: Client, status: int, needle: str
) -> None:
    _site(mock_http)
    mock_http.get(PAGE).mock(return_value=httpx.Response(status))
    with pytest.raises(FetchError) as info:
        await client.aload(PAGE)
    assert needle in str(info.value)
    assert info.value.trace is not None
    assert info.value.trace.steps[-1].status_code == status


async def test_network_error(mock_http: respx.MockRouter, client: Client) -> None:
    _site(mock_http)
    mock_http.get(PAGE).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FetchError, match="Network error"):
        await client.aload(PAGE)


async def test_cross_origin_redirect_rechecks_robots(
    mock_http: respx.MockRouter, client: Client
) -> None:
    _site(mock_http)
    other = "https://other.example"
    mock_http.get(PAGE).mock(
        return_value=httpx.Response(301, headers={"location": f"{other}/moved"})
    )
    mock_http.get(f"{other}/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /\n")
    )
    mock_http.get(f"{other}/.well-known/tdmrep.json").mock(return_value=httpx.Response(404))
    mock_http.get(f"{other}/ai.txt").mock(return_value=httpx.Response(404))
    mock_http.get(f"{other}/moved").mock(
        return_value=httpx.Response(200, text="<p>x</p>", headers={"content-type": HTML})
    )
    with pytest.raises(RobotsDisallowed):
        await client.aload(PAGE)


async def test_plain_text_response(mock_http: respx.MockRouter, client: Client) -> None:
    _site(mock_http)
    url = f"{SITE}/notes.md"
    mock_http.get(url).mock(
        return_value=httpx.Response(
            200,
            text="# Notes\n\nFirst paragraph.\n\nSecond paragraph.",
            headers={"content-type": "text/markdown"},
        )
    )
    doc = await client.aload(url)
    assert doc.markdown == "# Notes\n\nFirst paragraph.\n\nSecond paragraph."
    assert doc.blocks[0].type.value == "heading"
    assert doc.blocks[0].provenance.kind == "text"


async def test_image_is_not_supported_yet(mock_http: respx.MockRouter, client: Client) -> None:
    _site(mock_http)
    url = f"{SITE}/scan.png"
    png = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10])
    mock_http.get(url).mock(
        return_value=httpx.Response(200, content=png, headers={"content-type": "image/png"})
    )
    with pytest.raises(UnsupportedSourceError, match="OCR"):
        await client.aload(url)


async def test_bare_domain_gets_https(mock_http: respx.MockRouter, client: Client) -> None:
    _site(mock_http)
    _page(mock_http, f"{SITE}/", fixture_text("article.html"))
    doc = await client.aload("fieldnotes.example/")
    assert doc.source == "fieldnotes.example/"
    assert doc.url == f"{SITE}/"


# ---------------------------------------------------------------- files + sync API


def test_load_local_files(tmp_path: Path) -> None:
    doc = load(FIXTURES / "article.html")
    assert doc.markdown.startswith("# Understanding Tide Pools")
    assert doc.url is not None
    assert doc.url.startswith("file:")
    assert doc.compliance.robots_allowed is None
    assert doc.fetch_trace.steps[0].rung == "file"

    spa = load(str(FIXTURES / "spa_next.html"))
    assert spa.quality.extraction_method == "embedded"

    md = tmp_path / "x.md"
    md.write_text("## Title\n\nBody text.", encoding="utf-8")
    doc = load(md)
    assert [b.type.value for b in doc.blocks] == ["heading", "paragraph"]
    assert doc.blocks[0].level == 2
    assert doc.quality.extraction_confidence is None  # nothing to cross-check against


def test_load_rejects_unknown_sources(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedSourceError):
        load("definitely not a source")
    img = tmp_path / "scan.png"
    img.write_bytes(b"\x89PNG")
    with pytest.raises(UnsupportedSourceError, match="Phase 2"):
        load(img)


async def test_aload_and_load_guard() -> None:
    doc = await aload(FIXTURES / "article.html")
    assert doc.quality.word_count > 100
    with pytest.raises(RuntimeError, match="aload"):
        load(FIXTURES / "article.html")


def test_document_round_trips_as_json() -> None:
    doc = load(FIXTURES / "article.html")
    again = Document.model_validate_json(doc.model_dump_json())
    assert again == doc


async def test_ai_txt_disallow_makes_verdict_disallowed(
    mock_http: respx.MockRouter, client: Client
) -> None:
    _site(mock_http, ai_txt="# Spawning AI\nUser-Agent: *\nDisallow: *.html\nAllow: *.jpg\n")
    _page(mock_http, PAGE, fixture_text("article.html"))
    doc = await client.aload(PAGE)
    assert doc.compliance.ai_txt_allowed is False
    assert doc.compliance.ai_use == "disallowed"
    assert any("Disallow: *.html" in e for e in doc.compliance.evidence)
    assert any(s.rung == "ai.txt" for s in doc.fetch_trace.steps)


async def test_ai_txt_html_not_found_page_is_ignored(
    mock_http: respx.MockRouter, client: Client
) -> None:
    # Many sites answer unknown paths with a 200 HTML page instead of a 404.
    mock_http.get(f"{SITE}/robots.txt").mock(return_value=httpx.Response(404))
    mock_http.get(f"{SITE}/.well-known/tdmrep.json").mock(return_value=httpx.Response(404))
    _page(mock_http, f"{SITE}/ai.txt", "<html><body>Page not found. Disallow: /</body></html>")
    _page(mock_http, PAGE, fixture_text("article.html"))
    doc = await client.aload(PAGE)
    assert doc.compliance.ai_txt_allowed is None
    assert doc.compliance.ai_use != "disallowed"
