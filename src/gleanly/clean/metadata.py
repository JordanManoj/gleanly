from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin

from lxml.html import HtmlElement

from gleanly.models import Metadata


def iter_json_ld(root: HtmlElement) -> list[tuple[str, Any]]:
    """Return (xpath of the <script>, parsed JSON) for every JSON-LD block."""
    tree = root.getroottree()
    out: list[tuple[str, Any]] = []
    for script in root.iter("script"):
        if (script.get("type") or "").strip().lower() != "application/ld+json":
            continue
        raw = (script.text or "").strip()
        for junk in ("<!--", "-->", "<![CDATA[", "]]>"):
            raw = raw.replace(junk, "")
        try:
            out.append((tree.getpath(script), json.loads(raw)))
        except ValueError:
            continue
    return out


def json_ld_objects(data: Any) -> Iterator[dict[str, Any]]:
    """Flatten lists and @graph containers into individual JSON-LD objects."""
    if isinstance(data, list):
        for item in data:
            yield from json_ld_objects(item)
    elif isinstance(data, dict):
        if "@graph" in data:
            yield from json_ld_objects(data["@graph"])
        yield data


def _name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        return name if isinstance(name, str) else None
    if isinstance(value, list):
        names = [n for n in (_name(v) for v in value) if n]
        return ", ".join(names) or None
    return None


def extract_metadata(
    root: HtmlElement,
    *,
    url: str | None,
    status_code: int | None = None,
    content_type: str | None = None,
    json_ld: list[tuple[str, Any]] | None = None,
) -> Metadata:
    meta: dict[str, str] = {}
    for m in root.iter("meta"):
        key = (m.get("name") or m.get("property") or m.get("http-equiv") or "").strip().lower()
        content = (m.get("content") or "").strip()
        if key and content and key not in meta:
            meta[key] = content

    def first(*keys: str) -> str | None:
        for k in keys:
            if meta.get(k):
                return meta[k]
        return None

    canonical = None
    for link in root.iter("link"):
        rels = (link.get("rel") or "").lower().split()
        if "canonical" in rels and link.get("href"):
            href = link.get("href") or ""
            canonical = urljoin(url, href) if url else href
            break

    objects = [o for _, data in (json_ld or []) for o in json_ld_objects(data)]

    def from_ld(*keys: str) -> str | None:
        for obj in objects:
            for k in keys:
                if (v := _name(obj.get(k))) is not None:
                    return v
        return None

    title_el = root.find(".//title")
    title = title_el.text_content().strip() if title_el is not None else None
    html_el = root if root.tag == "html" else root.find(".//html")
    lang = html_el.get("lang") if html_el is not None else None

    return Metadata(
        title=title or first("og:title", "twitter:title") or from_ld("headline", "name"),
        description=first("description", "og:description", "twitter:description")
        or from_ld("description"),
        language=(lang or first("content-language", "og:locale") or None),
        canonical_url=canonical,
        author=first("author", "article:author") or from_ld("author"),
        published_at=first("article:published_time", "date") or from_ld("datePublished"),
        modified_at=first("article:modified_time") or from_ld("dateModified"),
        site_name=first("og:site_name", "application-name"),
        image=first("og:image", "twitter:image"),
        content_type=content_type,
        status_code=status_code,
        structured_data=[data for _, data in (json_ld or [])],
    )
