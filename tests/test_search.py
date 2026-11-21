"""search(): backends, fusion, fetching and ranking. All HTTP is mocked."""

from __future__ import annotations

import httpx
import pytest
import respx

from gleanly import Client
from gleanly.search import relevance, search_with
from gleanly.search.backends import Brave, RawHit, SearchBackendError, SearXNG, Wikipedia
from gleanly.search.fusion import fuse, normalise_url

WIKI = "https://en.wikipedia.org"
OTHER = "https://tides.example"
HTML = {"content-type": "text/html; charset=utf-8"}

ARTICLE = """<html><head><title>{title}</title></head><body><article>
<h1>{title}</h1>
<p>A tide pool is a rocky pool on the seashore that is separated from the sea at low
tide. Tide pools hold sea stars, anemones, crabs and snails, which must survive large
changes in temperature and salinity every day.</p>
<p>Visitors should step carefully, because the animals living in tide pools are easily
crushed, and should never take animals home from the shore.</p>
<p>Many coastal parks run guided walks at low tide so that children can see the pools
without harming them, and local schools use the walks for science lessons.</p>
</article></body></html>"""


def _site(router: respx.MockRouter, origin: str) -> None:
    for path in ("/robots.txt", "/.well-known/tdmrep.json", "/ai.txt"):
        router.get(f"{origin}{path}").mock(return_value=httpx.Response(404))


def _wiki_api(router: respx.MockRouter, titles: list[str]) -> respx.Route:
    payload = {
        "query": {
            "search": [
                {"title": t, "snippet": f'<span class="searchmatch">{t}</span> facts'}
                for t in titles
            ]
        }
    }
    return router.get(url__startswith=f"{WIKI}/w/api.php").mock(
        return_value=httpx.Response(200, json=payload)
    )


# ----------------------------------------------------------------------------- fusion
@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://www.Example.com/a/?utm_source=x#top", "http://example.com/a"),
        ("https://example.com/a?id=3&fbclid=zz", "https://example.com/a?id=3"),
    ],
)
def test_normalise_url_merges_variants(a: str, b: str) -> None:
    assert normalise_url(a) == normalise_url(b)


def test_fusion_rewards_agreement_between_engines() -> None:
    lists = {
        "one": [RawHit("https://a.example/x"), RawHit("https://shared.example/")],
        "two": [RawHit("https://b.example/y"), RawHit("https://www.shared.example")],
    }
    hits = fuse(lists)
    assert hits[0].url == "https://shared.example/"  # rank 2 twice beats rank 1 once
    assert sorted(hits[0].engines) == ["one", "two"]
    assert hits[0].ranks == {"one": 2, "two": 2}
    assert len(hits) == 3


def test_relevance() -> None:
    assert relevance("tide pool animals", "Tide pool animals", "animals live in tide pools") == 1.0
    assert relevance("tide pool animals", "Cars", "nothing related here") == 0.0
    assert 0 < relevance("tide pool volcano", "", "tide pool life") < 1


# --------------------------------------------------------------------------- backends
async def test_wikipedia_backend(mock_http: respx.MockRouter) -> None:
    route = _wiki_api(mock_http, ["Tide pool", "Rock pool (film)"])
    async with Client(min_delay=0) as c:
        hits = await Wikipedia().search(c.http, "tide pool", 5)
    assert [h.url for h in hits] == [f"{WIKI}/wiki/Tide_pool", f"{WIKI}/wiki/Rock_pool_(film)"]
    assert hits[0].snippet == "Tide pool facts"  # HTML highlighting removed
    sent = route.calls[0].request
    assert "gleanly" in sent.headers["user-agent"]  # honest User-Agent
    assert "srsearch=tide+pool" in str(sent.url)


async def test_brave_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    async with Client(min_delay=0) as c:
        with pytest.raises(SearchBackendError, match="BRAVE_API_KEY"):
            await Brave().search(c.http, "q", 5)


async def test_brave_backend(mock_http: respx.MockRouter) -> None:
    route = mock_http.get(url__startswith="https://api.search.brave.com/").mock(
        return_value=httpx.Response(
            200,
            json={"web": {"results": [{"url": f"{OTHER}/p", "title": "T", "description": "D"}]}},
        )
    )
    async with Client(min_delay=0) as c:
        hits = await Brave(api_key="secret").search(c.http, "tide", 5)
    assert hits == [RawHit(f"{OTHER}/p", "T", "D")]
    assert route.calls[0].request.headers["x-subscription-token"] == "secret"


async def test_searxng_backend(mock_http: respx.MockRouter) -> None:
    mock_http.get(url__startswith="http://localhost:8888/search").mock(
        return_value=httpx.Response(
            200, json={"results": [{"url": f"{OTHER}/q", "title": "Q", "content": "C"}]}
        )
    )
    async with Client(min_delay=0) as c:
        hits = await SearXNG(base_url="http://localhost:8888/").search(c.http, "tide", 5)
    assert hits == [RawHit(f"{OTHER}/q", "Q", "C")]


# ---------------------------------------------------------------------------- search()
async def test_search_fetches_scores_and_reports_failed_backends(
    mock_http: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    _wiki_api(mock_http, ["Tide pool", "Car"])
    _site(mock_http, WIKI)
    mock_http.get(f"{WIKI}/wiki/Tide_pool").mock(
        return_value=httpx.Response(200, text=ARTICLE.format(title="Tide pool"), headers=HTML)
    )
    mock_http.get(f"{WIKI}/wiki/Car").mock(
        return_value=httpx.Response(
            200, text=ARTICLE.format(title="Car").replace("tide pool", "road"), headers=HTML
        )
    )
    async with Client(min_delay=0, browser="never") as c:
        resp = await search_with(c, "tide pool animals", backends=["wikipedia", "brave"])
    assert resp.backends == ["wikipedia"]
    assert any("brave" in w and "BRAVE_API_KEY" in w for w in resp.warnings)
    top = resp.results[0]
    assert top.hit.url.endswith("/Tide_pool")
    assert top.document is not None
    assert top.document.quality.score > 0
    assert top.document.compliance.ai_use in ("allowed", "disallowed", "unclear")
    assert top.relevance is not None
    assert top.score >= resp.results[-1].score


async def test_search_can_drop_pages_that_disallow_ai_use(mock_http: respx.MockRouter) -> None:
    _wiki_api(mock_http, ["Tide pool", "Rock pool"])
    _site(mock_http, WIKI)
    mock_http.get(f"{WIKI}/wiki/Tide_pool").mock(
        return_value=httpx.Response(200, text=ARTICLE.format(title="Tide pool"), headers=HTML)
    )
    mock_http.get(f"{WIKI}/wiki/Rock_pool").mock(
        return_value=httpx.Response(
            200,
            text=ARTICLE.format(title="Rock pool"),
            headers={**HTML, "x-robots-tag": "noai"},
        )
    )
    async with Client(min_delay=0, browser="never") as c:
        resp = await search_with(c, "tide pool", backends=["wikipedia"], exclude_disallowed=True)
    urls = [r.hit.url for r in resp.results]
    assert urls == [f"{WIKI}/wiki/Tide_pool"]
    assert any("AI use disallowed" in w for w in resp.warnings)


async def test_search_keeps_hits_whose_page_fails(mock_http: respx.MockRouter) -> None:
    _wiki_api(mock_http, ["Gone"])
    _site(mock_http, WIKI)
    mock_http.get(f"{WIKI}/wiki/Gone").mock(return_value=httpx.Response(404))
    async with Client(min_delay=0, browser="never") as c:
        resp = await search_with(c, "gone", backends=["wikipedia"])
    assert resp.results[0].document is None
    assert resp.results[0].error


async def test_search_without_fetch(mock_http: respx.MockRouter) -> None:
    _wiki_api(mock_http, ["Tide pool"])
    async with Client(min_delay=0) as c:
        resp = await search_with(c, "tide pool", backends=["wikipedia"], fetch=False)
    assert resp.results[0].document is None
    assert resp.results[0].hit.title == "Tide pool"


def test_unknown_backend_name() -> None:
    from gleanly.search import _resolve

    with pytest.raises(ValueError, match="Unknown backend"):
        _resolve(["google"])


def test_cli_search_lists_hits(
    mock_http: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    from gleanly.cli import main

    _wiki_api(mock_http, ["Tide pool"])
    assert main(["search", "tide pool", "-b", "wikipedia", "--no-fetch"]) == 0
    out = capsys.readouterr()
    assert "## 1. Tide pool" in out.out
    assert "found by wikipedia #1" in out.out
    assert "1 results from wikipedia" in out.err
