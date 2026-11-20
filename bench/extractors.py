"""Adapters: every extractor takes (html, url) and returns plain text.

Baselines are optional: install them with `uv sync --group bench`.
"""

from __future__ import annotations

from collections.abc import Callable

from lxml.html import HtmlElement

from gleanly.clean import Extraction, extract_html, markdown_to_plain, parse_html
from gleanly.clean.blocks import rescue
from gleanly.clean.comments import with_comments
from gleanly.fetch import router
from gleanly.fetch.embedded import extract_embedded

Extractor = Callable[[str, "str | None"], str]


def gleanly_pipeline(
    html: str, url: str | None, *, include_comments: bool = False
) -> tuple[Extraction, HtmlElement]:
    """gleanly's offline pipeline: visible-text extraction, then the embedded-data rung."""
    root = parse_html(html)
    extraction = extract_html(root, url, method="http", include_comments=include_comments)
    if router.is_poor(extraction) or router.looks_js_rendered(root, extraction):
        embedded = extract_embedded(root, url)
        if router.better(embedded, extraction) and embedded is not None:
            extraction = embedded
    extraction = rescue(extraction, root) or extraction
    if include_comments and extraction.method == "embedded":
        extraction = with_comments(extraction, root)
    return extraction, root


def gleanly_extract(html: str, url: str | None) -> str:
    extraction, _ = gleanly_pipeline(html, url)
    return "\n".join(markdown_to_plain(b.text) for b in extraction.blocks)


def gleanly_comments_extract(html: str, url: str | None) -> str:
    extraction, _ = gleanly_pipeline(html, url, include_comments=True)
    return "\n".join(markdown_to_plain(b.text) for b in extraction.blocks)


def _trafilatura(html: str, url: str | None) -> str:
    import trafilatura

    return trafilatura.extract(html, url=url, favor_precision=False) or ""


def _readability(html: str, url: str | None) -> str:
    from readability import Document

    summary = Document(html, url=url).summary(html_partial=True)
    return parse_html(summary).text_content()


def available() -> dict[str, Extractor]:
    out: dict[str, Extractor] = {
        "gleanly": gleanly_extract,
        "gleanly-comments": gleanly_comments_extract,  # include_comments=True
    }
    try:
        import trafilatura  # noqa: F401

        out["trafilatura"] = _trafilatura
    except ImportError:
        pass
    try:
        import readability  # noqa: F401

        out["readability"] = _readability
    except ImportError:
        pass
    return out
