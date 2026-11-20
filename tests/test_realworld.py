"""Regression tests on pages modelled on real-world layouts (news, docs, blog, shop).

The pages are original content written for these tests (third-party pages are never
committed). Two checks per page:

- **golden file**: the exact Markdown is stored next to the page as ``<name>.expected.md``;
  any change shows up as a diff. After an intended change, regenerate with
  ``GLEANLY_UPDATE_GOLDEN=1 uv run pytest tests/test_realworld.py`` and review the diff.
- **must / must not**: text that has to be there (the article) and text that must never
  leak in (cookie banners, menus), so a reviewer can see what each page is about.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass, field

import pytest

from gleanly import load

from .conftest import FIXTURES

PAGES = FIXTURES / "realworld"
UPDATE = os.environ.get("GLEANLY_UPDATE_GOLDEN") == "1"


@dataclass
class Case:
    name: str
    must: list[str]
    must_not: list[str]
    comments: bool = False
    min_confidence: float = 0.7
    extra: dict[str, object] = field(default_factory=dict)


CASES = [
    Case(
        "news",
        must=[
            "# River towns vote to share one flood warning system",  # headline outside body
            "## What changes for residents",
            "- Sirens will sound in all four towns",
            "Two councillors in Lower Marsh voted against",
        ],
        must_not=[
            "cookies",
            "Subscribe",
            "Share on",
            "Related stories",
            "morning briefing",
            "Most read",
            "All rights reserved",
            "Photo: Courier staff",
        ],
    ),
    Case(
        "docs",
        must=[
            "# Configuring retries",
            "| `max_attempts` | 3 | Total tries, including the first |",
            "```python\nfrom tidekeeper import Client, RetryPolicy",
            "Delays are capped at 30 seconds",
        ],
        must_not=["Edit", "Installation", "Quickstart", "Search", "Previous:", "Built with"],
    ),
    Case(
        "blog_comments",
        comments=True,
        must=[
            "# Why my sourdough stopped rising (and the fix)",
            "> Watch the dough, not the timer.",
            "proofing in the oven with just the light on",
            "straight-sided container",
        ],
        must_not=[
            "Posted on",
            "Share this",
            "Reply",
            "email address",
            "Recent posts",
            "Proudly powered",
        ],
        extra={"comment_blocks": 2, "license": "CC-BY-4.0"},
    ),
    Case(
        "product",
        must=[
            "# Field Thermos 750 ml",
            "- Capacity: 750 ml",
            "five-year guarantee against leaks",
        ],
        must_not=["Free shipping", "Add to cart", "Cart (0)", "You may also like", "Returns"],
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_realworld_page(case: Case) -> None:
    doc = load(str(PAGES / f"{case.name}.html"), include_comments=case.comments)
    md = doc.markdown

    golden = PAGES / f"{case.name}.expected.md"
    if UPDATE or not golden.exists():
        golden.write_text(md + "\n", encoding="utf-8", newline="\n")
    expected = golden.read_text(encoding="utf-8").rstrip("\n")
    if md != expected:
        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(), md.splitlines(), "expected", "got", lineterm=""
            )
        )
        pytest.fail(
            f"{case.name}: Markdown changed (set GLEANLY_UPDATE_GOLDEN=1 if intended)\n{diff}"
        )

    for text in case.must:
        assert text in md, f"{case.name}: missing {text!r}"
    for text in case.must_not:
        assert text not in md, f"{case.name}: boilerplate leaked: {text!r}"
    conf = doc.quality.extraction_confidence
    assert conf is not None
    assert conf >= case.min_confidence
    if "comment_blocks" in case.extra:
        comments = [b for b in doc.blocks if b.role == "comment" and b.type == "paragraph"]
        assert len(comments) == case.extra["comment_blocks"]
    if "license" in case.extra:
        assert doc.compliance.license == case.extra["license"]
