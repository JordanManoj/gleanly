"""``search(query)``: web search with trust, compliance and provenance on every result.

Pipeline:

1. **Query** every configured backend in parallel (official APIs only; see backends.py).
2. **Fuse** the result lists with reciprocal rank fusion; pages several engines agree on
   rise to the top.
3. **Fetch** the top pages through the normal ``load()`` pipeline, so each result is a
   full :class:`~gleanly.models.Document`: clean Markdown, trust score, AI-use compliance
   verdict and block provenance. robots.txt and per-host rate limits apply as usual.
4. **Rank** v0: lexical relevance of the page to the query, combined with the fused rank
   and weighted by the page's trust score. Pages whose AI use is disallowed can be
   dropped (``exclude_disallowed=True``). The weights are hand-set for now and will be
   tuned on a search benchmark before they are relied on.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Any

from gleanly.client import Client
from gleanly.config import LoadOptions
from gleanly.errors import AcquisitionError
from gleanly.models import SearchHit, SearchResponse, SearchResult
from gleanly.search.backends import (
    BACKENDS,
    Backend,
    RawHit,
    SearchBackendError,
    default_backends,
)
from gleanly.search.fusion import fuse, normalise_url

_WORD = re.compile(r"\w+", re.UNICODE)
_STOP_TEXT = (
    "a an and are as at be by for from how in is it of on or that the this to was what "
    "when where which who why with does do did"
)
_STOP = frozenset(_STOP_TEXT.split())
# Ranking v0 (hand-set; to be tuned on a search benchmark).
W_RELEVANCE = 0.6
W_FUSION = 0.4
TRUST_FLOOR = 0.5  # score is scaled by TRUST_FLOOR + (1 - TRUST_FLOOR) * trust


def _stem(t: str) -> str:
    """Very light English plural folding: "pools" -> "pool", but "glass" stays."""
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def _terms(text: str) -> list[str]:
    return [_stem(t) for t in (m.lower() for m in _WORD.findall(text)) if t not in _STOP]


def relevance(query: str, title: str, text: str) -> float:
    """0-1: share of the query's distinct terms in the page, with a bonus for the title.

    (share in body + 0.5 x share in title) / 1.5, so a page with every term in both its
    text and its title scores 1.
    """
    q = set(_terms(query))
    if not q:
        return 0.0
    body = set(_terms(text))
    head = set(_terms(title))
    in_body = sum(t in body for t in q) / len(q)
    in_title = sum(t in head for t in q) / len(q)
    return (in_body + 0.5 * in_title) / 1.5


def _resolve(backends: Sequence[str | Backend] | None) -> list[Backend]:
    if backends is None:
        return default_backends()
    out: list[Backend] = []
    for b in backends:
        if isinstance(b, str):
            if b not in BACKENDS:
                raise ValueError(f"Unknown backend {b!r}; choose from {sorted(BACKENDS)}")
            out.append(BACKENDS[b]())
        else:
            out.append(b)
    return out


async def _query_all(
    client: Client, backends: list[Backend], query: str, count: int
) -> tuple[dict[str, list[RawHit]], list[str]]:
    async def one(b: Backend) -> tuple[str, list[RawHit] | str]:
        try:
            return b.name, await b.search(client.http, query, count)
        except SearchBackendError as exc:
            return b.name, str(exc)

    lists: dict[str, list[RawHit]] = {}
    warnings: list[str] = []
    for name, res in await asyncio.gather(*(one(b) for b in backends)):
        if isinstance(res, str):
            warnings.append(f"Backend {name} failed: {res}")
        else:
            lists[name] = res
    return lists, warnings


def _rank(query: str, results: list[SearchResult]) -> None:
    top = max((r.hit.fused_score for r in results), default=0.0) or 1.0
    for r in results:
        fusion = r.hit.fused_score / top
        doc = r.document
        if doc is None:
            rel = relevance(query, r.hit.title, r.hit.snippet)
            trust = 0.0
        else:
            rel = relevance(query, doc.metadata.title or r.hit.title, doc.markdown)
            trust = doc.quality.score
        r.relevance = round(rel, 3)
        base = W_RELEVANCE * rel + W_FUSION * fusion
        r.score = round(base * (TRUST_FLOOR + (1 - TRUST_FLOOR) * trust), 4)
    results.sort(key=lambda r: -r.score)


async def search_with(
    client: Client,
    query: str,
    *,
    backends: Sequence[str | Backend] | None = None,
    max_results: int = 5,
    candidates: int = 10,
    fetch: bool = True,
    exclude_disallowed: bool = False,
) -> SearchResponse:
    """Run a search with an existing :class:`Client` (shared rate limits and caches)."""
    chosen = _resolve(backends)
    lists, warnings = await _query_all(client, chosen, query, candidates)
    hits: list[SearchHit] = fuse(lists)[: max(candidates, max_results)]
    if not lists:
        warnings.append("No backend answered; nothing to return.")

    async def fetch_one(hit: SearchHit) -> SearchResult:
        if not fetch:
            return SearchResult(hit=hit)
        try:
            return SearchResult(hit=hit, document=await client.aload(hit.url))
        except AcquisitionError as exc:
            return SearchResult(hit=hit, error=str(exc))

    pool = hits[: max_results * 2] if fetch else hits  # fetch a margin for drops/failures
    results = list(await asyncio.gather(*(fetch_one(h) for h in pool)))
    if exclude_disallowed:
        dropped = [
            r for r in results if r.document and r.document.compliance.ai_use == "disallowed"
        ]
        if dropped:
            warnings.append(f"{len(dropped)} result(s) dropped: AI use disallowed by the site.")
        results = [r for r in results if r not in dropped]
    _rank(query, results)
    return SearchResponse(
        query=query, results=results[:max_results], backends=sorted(lists), warnings=warnings
    )


async def asearch(
    query: str,
    *,
    backends: Sequence[str | Backend] | None = None,
    max_results: int = 5,
    fetch: bool = True,
    exclude_disallowed: bool = False,
    options: LoadOptions | None = None,
    **overrides: Any,
) -> SearchResponse:
    """Search the web and return cleaned, scored results (async).

    ``backends``: names ("wikipedia", "brave", "searxng") or backend objects; default is
    every backend configured here. Keyword overrides map to :class:`LoadOptions`.
    """
    async with Client(options, **overrides) as client:
        return await search_with(
            client,
            query,
            backends=backends,
            max_results=max_results,
            fetch=fetch,
            exclude_disallowed=exclude_disallowed,
        )


def search(query: str, **kwargs: Any) -> SearchResponse:
    """Search the web and return cleaned, scored results. See :func:`asearch`."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(asearch(query, **kwargs))
    raise RuntimeError(
        "search() was called from a running event loop; use `await asearch(...)` instead."
    )


__all__ = ["asearch", "normalise_url", "relevance", "search", "search_with"]
