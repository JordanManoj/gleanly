"""Block-classifier extractor: gleanly's second, independent view of a page.

The main extractor (html.py) picks one content container, Readability-style. This one
shares nothing with it: it splits the page into text blocks at block-level tags and
classifies each block on its own (jusText/boilerpipe-style: length, link density,
sentence punctuation and its neighbours). It never looks at class names or containers.

It has two jobs:

- **Cross-check** (quality/crosscheck.py): words of the main extraction that this view
  also kept are "supported"; that gives the extraction confidence.
- **Rescue**: when the main extractor finds (almost) nothing but this view finds plenty,
  the page is laid out in a way container scoring does not handle, so this view is used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml.html import HtmlElement

from gleanly.clean.html import (
    BLOCK_TAGS,
    HEADINGS,
    SKIP_TAGS,
    Extraction,
    RawBlock,
    _is_element,
    _norm,
)
from gleanly.models import BlockType

_SENTENCE_END = re.compile(r"[.!?。！？]['\")\]”’]?(\s|$)")  # noqa: RUF001 (CJK stops)

# Block classes. Tuned on dev splits only; results are flat across nearby values.
BAD_LINK_DENSITY = 0.4
GOOD_WORDS = 20
GOOD_LINK_DENSITY = 0.25
SHORT_WORDS = 7
# Rescue: use this view when the main extraction has at most RESCUE_WORDS words and this
# view has RESCUE_RATIO times more (twice as many if the main one is nearly empty).
RESCUE_WORDS = 150
RESCUE_RATIO = 6
NEARLY_EMPTY = 50
MIN_RESCUE_WORDS = 20


@dataclass
class Segment:
    el: HtmlElement  # element whose own text this is (provenance)
    text: str
    link_chars: int

    @property
    def words(self) -> int:
        return len(self.text.split())


def _page_root(root: HtmlElement) -> HtmlElement:
    """The <body>, unless broken markup left the text outside it."""
    body = root.find("body")
    if body is not None and len(body.text_content().strip()) > 50:
        return body
    return root


def segments(root: HtmlElement, skip: frozenset[str] | set[str] = SKIP_TAGS) -> list[Segment]:
    """Split the page into text blocks at block-level tags, in document order.

    Elements whose tag is in ``skip`` are left out together with their text.
    """
    out: list[Segment] = []

    def flush(el: HtmlElement, parts: list[str], links: int) -> None:
        text = _norm(" ".join(parts)).strip()
        if text:
            out.append(Segment(el, text, links))

    def rec(el: HtmlElement) -> None:
        parts, links = [el.text or ""], 0
        for child in el:
            if _is_element(child) and child.tag not in skip:
                if child.tag in BLOCK_TAGS:
                    flush(el, parts, links)
                    parts, links = [], 0
                    rec(child)
                else:
                    parts.append(child.text_content())
                    anchors = [child] if child.tag == "a" else child.iter("a")
                    links += sum(len(_norm(a.text_content()).strip()) for a in anchors)
            parts.append(child.tail or "")
        flush(el, parts, links)

    rec(_page_root(root))
    return out


def labels(segs: list[Segment]) -> list[str]:
    """Context-free class of each block: "good" (prose), "near", "short" or "bad"."""
    out: list[str] = []
    for seg in segs:
        density = seg.link_chars / len(seg.text)
        if density > BAD_LINK_DENSITY:
            out.append("bad")
        elif (
            seg.words >= GOOD_WORDS
            and density < GOOD_LINK_DENSITY
            and _SENTENCE_END.search(seg.text)
        ):
            out.append("good")
        elif seg.words < SHORT_WORDS:
            out.append("short")
        else:
            out.append("near")
    return out


def classify(segs: list[Segment]) -> list[bool]:
    """True for blocks this method considers main content."""
    labels_ = labels(segs)

    def nearest(i: int, step: int) -> str:
        j = i + step
        while 0 <= j < len(labels_):
            if labels_[j] != "short":
                return labels_[j]
            j += step
        return "bad"

    keep: list[bool] = []
    for i, label in enumerate(labels_):
        if label == "good":
            keep.append(True)
        elif label == "near":  # medium block next to real prose
            keep.append("good" in (nearest(i, -1), nearest(i, 1)))
        elif label == "short":  # short block inside a run of prose
            keep.append(nearest(i, -1) == "good" and nearest(i, 1) == "good")
        else:
            keep.append(False)
    return keep


def content_segments(root: HtmlElement) -> list[Segment]:
    segs = segments(root)
    return [s for s, k in zip(segs, classify(segs), strict=True) if k]


def reference_text(root: HtmlElement) -> str:
    """This view of the page's main content, as plain text."""
    return "\n".join(s.text for s in content_segments(root))


def prose_text(root: HtmlElement) -> str:
    """Only the blocks that read as prose on their own (long, few links, sentences)."""
    segs = segments(root)
    return "\n".join(s.text for s, lab in zip(segs, labels(segs), strict=True) if lab == "good")


def extract_blocks(root: HtmlElement, method: str) -> Extraction:
    """Run this view as a full extractor, with an XPath for every block."""
    tree = root.getroottree()
    blocks: list[RawBlock] = []
    link_chars = 0
    for seg in content_segments(root):
        path = tree.getpath(seg.el)
        if seg.el.tag in HEADINGS:
            level = int(seg.el.tag[1])
            blocks.append(RawBlock(BlockType.HEADING, f"{'#' * level} {seg.text}", path, level))
        else:
            blocks.append(RawBlock(BlockType.PARAGRAPH, seg.text, path))
        link_chars += seg.link_chars
    page_chars = len(_norm(_page_root(root).text_content()).strip())
    return Extraction(
        blocks, method, link_chars=link_chars, page_chars=page_chars, extractor="blocks"
    )


def rescue(extraction: Extraction, root: HtmlElement) -> Extraction | None:
    """The block view, if the main extraction missed most of the page's prose."""
    words = extraction.word_count
    if words > RESCUE_WORDS or extraction.extractor != "main" or extraction.method == "embedded":
        return None
    candidate = extract_blocks(root, extraction.method)
    ratio = 2 if words <= NEARLY_EMPTY else RESCUE_RATIO
    if candidate.word_count > max(words * ratio, MIN_RESCUE_WORDS):
        return candidate
    return None


__all__ = [
    "Segment",
    "classify",
    "content_segments",
    "extract_blocks",
    "labels",
    "prose_text",
    "reference_text",
    "rescue",
    "segments",
]
