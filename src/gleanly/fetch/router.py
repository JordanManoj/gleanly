"""Decide when to climb the fetch ladder.

Phase 4 will add learned per-domain routing (remember which rung works per site).
"""

from __future__ import annotations

from lxml.html import HtmlElement

from gleanly.clean.html import Extraction

POOR_WORD_COUNT = 80
_APP_ROOT_IDS = ("root", "app", "__next", "__nuxt", "___gatsby", "svelte", "main-app")


def is_poor(extraction: Extraction) -> bool:
    return extraction.word_count < POOR_WORD_COUNT


def looks_js_rendered(root: HtmlElement, extraction: Extraction) -> bool:
    """Heuristic: little server-rendered text plus signs of a client-side app."""
    if extraction.word_count >= 150:
        return False
    for el in root.iter():
        if isinstance(el.tag, str) and el.get("id") in _APP_ROOT_IDS:
            return True
    script_srcs = sum(1 for s in root.iter("script") if s.get("src"))
    noscript_js = any("javascript" in n.text_content().lower() for n in root.iter("noscript"))
    return script_srcs >= 3 or noscript_js


def better(candidate: Extraction | None, current: Extraction) -> bool:
    return candidate is not None and candidate.word_count > max(
        current.word_count, POOR_WORD_COUNT // 2
    )
