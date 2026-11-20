"""Extraction confidence from an independent second opinion.

The main extractor picks one content container (Readability-style). The block
classifier in clean/blocks.py is a structurally different second opinion. Each extracted
block is checked against it: words that the independent method also kept are "supported".

Two sides are checked, like precision and recall:

- **support**: share of the extracted words the independent method also kept (catches
  leaked boilerplate);
- **coverage**: share of the independent method's content that the extraction contains
  (catches missed prose, the more common failure across the eight benchmark datasets).

confidence = support x sqrt(coverage): coverage is the noisier side (the second opinion
may keep prose that is not main content), so it gets less weight.
See bench/README.md for how well it predicts accuracy.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from lxml.html import HtmlElement

from gleanly.clean.blocks import prose_text, reference_text
from gleanly.clean.html import Extraction
from gleanly.clean.html import markdown_to_plain as _plain
from gleanly.models import BlockType

_TOKEN = re.compile(r"\w+", re.UNICODE)

# Below this many words the second opinion is too thin to judge (e.g. JS-rendered pages).
MIN_REFERENCE_WORDS = 50
# The second opinion judges prose only; tables, code and images are left unchecked.
UNCHECKED_TYPES = {BlockType.TABLE, BlockType.CODE, BlockType.IMAGE}
# Under this confidence a warning is added to the quality report (dev split of all eight
# datasets: flags ~1 page in 6; flagged pages average F1 0.72, the rest 0.94).
LOW_CONFIDENCE = 0.7


@dataclass
class CrossCheck:
    """Result of checking an extraction against the independent block classifier."""

    confidence: float | None
    block_support: list[float | None] = field(default_factory=list)
    reference_words: int = 0
    support: float | None = None  # share of extracted words the second opinion also kept
    coverage: float | None = None  # share of the second opinion's words that were extracted


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def cross_check(extraction: Extraction, root: HtmlElement | None) -> CrossCheck:
    """Score each extracted block by how much of it the independent method also kept."""
    if root is None or not extraction.blocks or extraction.extractor == "blocks":
        # Nothing to compare, or the text already *is* the second opinion.
        return CrossCheck(None, [None] * len(extraction.blocks))
    reference = Counter(_tokens(reference_text(root)))
    ref_words = sum(reference.values())
    if ref_words < MIN_REFERENCE_WORDS:
        return CrossCheck(None, [None] * len(extraction.blocks), ref_words)
    support: list[float | None] = []
    supported = total = 0
    remaining = reference.copy()
    extracted: Counter[str] = Counter()
    for block in extraction.blocks:
        words = _tokens(_plain(block.text))
        extracted.update(words)
        if not words or block.type in UNCHECKED_TYPES:
            support.append(None)
            continue
        hit = 0
        for w in words:  # multiset: each reference word supports one extracted word
            if remaining[w] > 0:
                remaining[w] -= 1
                hit += 1
        support.append(round(hit / len(words), 3))
        supported += hit
        total += len(words)
    if not total:
        return CrossCheck(None, support, ref_words)
    precision_side = supported / total
    # Coverage is judged on prose only: short kept blocks (cookie notes, footers) are where
    # the second opinion itself is least sure.
    prose = Counter(_tokens(prose_text(root)))
    prose_words = sum(prose.values())
    recall_side = sum((prose & extracted).values()) / prose_words if prose_words else 1.0
    return CrossCheck(
        round(precision_side * recall_side**0.5, 3),
        support,
        ref_words,
        support=round(precision_side, 3),
        coverage=round(recall_side, 3),
    )


__all__ = ["LOW_CONFIDENCE", "CrossCheck", "cross_check", "reference_text"]
