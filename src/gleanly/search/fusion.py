"""Merge result lists from several backends: URL normalisation + reciprocal rank fusion.

Reciprocal rank fusion (Cormack, Clarke and Buettcher, SIGIR 2009) scores each URL by
the sum of 1 / (k + rank) over the lists it appears in. It needs no score calibration
between engines, and a page that several independent engines rank highly beats a page
that only one engine likes: agreement between sources, at the ranking level.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from gleanly.models import SearchHit
from gleanly.search.backends import RawHit

RRF_K = 60  # the constant from the original paper; damps the weight of top ranks
_TRACKING = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref_src")


def normalise_url(url: str) -> str:
    """One key per page: lower-case host, no fragment, no tracking parameters, no
    trailing slash, http and https treated alike."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith(_TRACKING)
        ]
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, query, ""))


def fuse(lists: dict[str, list[RawHit]], k: int = RRF_K) -> list[SearchHit]:
    """Merge per-backend result lists into one list, best first."""
    merged: dict[str, SearchHit] = {}
    for engine, hits in lists.items():
        seen: set[str] = set()
        for rank, raw in enumerate(hits, start=1):
            key = normalise_url(raw.url)
            if key in seen:  # a backend listing the same page twice counts once
                continue
            seen.add(key)
            hit = merged.get(key)
            if hit is None:
                hit = merged[key] = SearchHit(url=raw.url, title=raw.title, snippet=raw.snippet)
            hit.engines.append(engine)
            hit.ranks[engine] = rank
            hit.fused_score += 1.0 / (k + rank)
            if not hit.snippet and raw.snippet:
                hit.snippet = raw.snippet
    return sorted(merged.values(), key=lambda h: (-h.fused_score, min(h.ranks.values())))


__all__ = ["RRF_K", "fuse", "normalise_url"]
