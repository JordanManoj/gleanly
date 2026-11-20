"""Optional reader comments (``LoadOptions.include_comments``).

Main-content extraction drops comment sections on purpose: for most AI uses they are
noise. Some users want them (forum threads, discussion datasets), and benchmarks
disagree on whether they count as content, so they are opt-in.

Method: comment sections are found by their class/id names (``comments``, ``disqus`` ...),
then only the blocks that the block classifier (clean/blocks.py) labels as prose are
kept. That drops the furniture around each comment ("Reply", dates, avatars, vote
counts, the reply form) without site-specific rules. Comment blocks carry
``role="comment"`` so they can be filtered out again downstream.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from lxml.html import HtmlElement

from gleanly.clean.blocks import labels, segments
from gleanly.clean.html import HEADINGS, SKIP_TAGS, Extraction, RawBlock, _is_element
from gleanly.models import BlockType

COMMENT_WORDS = {"comment", "comments", "commentlist", "disqus", "discussion", "replies"}
# Block classes kept inside a comment section: "near" adds medium-length comments.
KEEP_LABELS = {"good", "near"}
_SPLIT = re.compile(r"[\s_\-]+")
_SKIP = SKIP_TAGS | {"form"}


def _is_comment_section(el: HtmlElement) -> bool:
    hint = f"{el.get('class') or ''} {el.get('id') or ''}".lower()
    return bool(hint.strip()) and bool(set(_SPLIT.split(hint)) & COMMENT_WORDS)


def _hidden(el: HtmlElement) -> bool:
    for node in (el, *el.iterancestors()):
        style = (node.get("style") or "").replace(" ", "").lower()
        if node.get("hidden") is not None or "display:none" in style:
            return True
    return False


def comment_sections(
    body: HtmlElement,
    container: HtmlElement | None,
    already_extracted: Callable[[HtmlElement], bool] = lambda _: False,
) -> list[HtmlElement]:
    """Outermost comment sections that are not the article and not already extracted."""
    found: list[HtmlElement] = []
    for el in body.iter():
        if not _is_element(el) or not _is_comment_section(el):
            continue
        if container is not None and (
            el is container or any(a is el for a in container.iterancestors())
        ):
            continue  # e.g. WordPress' <body class="comments-open"> wraps the article too
        if any(f is a for f in found for a in el.iterancestors()):
            continue  # inside a section we already have
        if already_extracted(el) or _hidden(el):
            continue
        found.append(el)
    return found


def comment_blocks(sections: list[HtmlElement]) -> list[RawBlock]:
    out: list[RawBlock] = []
    for section in sections:
        tree = section.getroottree()
        segs = segments(section, _SKIP)  # forms: "Leave a reply" and its notes
        for seg, label in zip(segs, labels(segs), strict=True):
            if label not in KEEP_LABELS:
                continue
            path = tree.getpath(seg.el)
            if seg.el.tag in HEADINGS:  # "2 thoughts on ...": keep the section's structure
                level = int(seg.el.tag[1])
                text = f"{'#' * level} {seg.text}"
                out.append(RawBlock(BlockType.HEADING, text, path, level, role="comment"))
            else:
                out.append(RawBlock(BlockType.PARAGRAPH, seg.text, path, role="comment"))
    return out


def with_comments(extraction: Extraction, root: HtmlElement) -> Extraction:
    """Add the page's comments to text that came from elsewhere (e.g. embedded JSON-LD)."""
    if any(b.role == "comment" for b in extraction.blocks):
        return extraction
    body = root.find("body")
    found = comment_blocks(comment_sections(body if body is not None else root, None))
    if not found:
        return extraction
    extraction.blocks = [*extraction.blocks, *found]
    extraction.refresh()
    return extraction


__all__ = ["COMMENT_WORDS", "comment_blocks", "comment_sections", "with_comments"]
