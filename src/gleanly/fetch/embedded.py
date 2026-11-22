"""Rung 2: use data the page already ships instead of rendering it.

Many sites embed the full article in JSON-LD (``articleBody``) or in framework
state such as Next.js ``__NEXT_DATA__``. Reading it is cheaper and more faithful
than running a browser.

Framework state also holds text the page never shows (other countries' delivery terms,
other languages, A/B variants). So when the page itself shows real text, a state string
is kept only if it is visible on the page; on a page that is rendered by JavaScript (little
visible text) everything that reads as prose is kept. Repeated strings are kept once.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from lxml.html import HtmlElement

from gleanly.clean.html import Extraction, RawBlock, extract_fragment, markdown_to_plain
from gleanly.clean.metadata import iter_json_ld, json_ld_objects
from gleanly.models import BlockType

_HTMLISH = re.compile(r"<(p|div|h[1-6]|ul|ol|br|span|a|strong|em)[\s>/]", re.I)
_STATE_SCRIPT_IDS = ("__NEXT_DATA__", "__NUXT_DATA__", "__APOLLO_STATE__")
MIN_WORDS = 40
# A page showing at least this many words is not JavaScript-only: state strings must be
# visible on it to count.
VISIBLE_MIN_WORDS = 150


def _text_blocks(text: str, path: str) -> list[RawBlock]:
    paragraphs = re.split(r"\n\s*\n|\r\n\s*\r\n", text) if "\n\n" in text else text.split("\n")
    return [
        RawBlock(BlockType.PARAGRAPH, p.strip(), path, kind="embedded")
        for p in paragraphs
        if p.strip()
    ]


def _body_blocks(body: str, path: str, base_url: str | None) -> list[RawBlock]:
    if _HTMLISH.search(body):
        return extract_fragment(body, base_url, path_prefix=f"{path} :: ", kind="embedded")
    return _text_blocks(body, path)


def _walk_strings(data: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(data, dict):
        for k, v in data.items():
            yield from _walk_strings(v, f"{path}.{k}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            yield from _walk_strings(v, f"{path}[{i}]")
    elif isinstance(data, str):
        yield path, data


def _looks_like_prose(s: str) -> bool:
    if len(s.split()) < MIN_WORDS or s.lstrip().startswith(("http://", "https://", "{", "[")):
        return False
    return ". " in s or "</p>" in s


def _from_json_ld(root: HtmlElement, base_url: str | None) -> list[RawBlock]:
    blocks: list[RawBlock] = []
    for script_path, data in iter_json_ld(root):
        for i, obj in enumerate(json_ld_objects(data)):
            body = obj.get("articleBody") or obj.get("text")
            if not isinstance(body, str) or len(body.split()) < MIN_WORDS:
                continue
            key = "articleBody" if "articleBody" in obj else "text"
            headline = obj.get("headline") or obj.get("name")
            if isinstance(headline, str) and headline.strip():
                blocks.append(
                    RawBlock(
                        BlockType.HEADING,
                        f"# {headline.strip()}",
                        f"{script_path} $[{i}].headline",
                        1,
                        kind="embedded",
                    )
                )
            blocks += _body_blocks(body, f"{script_path} $[{i}].{key}", base_url)
    return blocks


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()  # split() also breaks on no-break spaces


_VISIBLE_XPATH = (
    "//text()[not(ancestor::script or ancestor::style or ancestor::noscript or ancestor::template)]"
)


def visible_text(root: HtmlElement) -> str:
    """The page's own text (not scripts or styles), normalised for substring checks."""
    return _norm(" ".join(root.xpath(_VISIBLE_XPATH)))


def _from_state_scripts(root: HtmlElement, base_url: str | None) -> list[RawBlock]:
    tree = root.getroottree()
    blocks: list[RawBlock] = []
    seen: set[str] = set()
    visible = visible_text(root)
    check_visible = len(visible.split()) >= VISIBLE_MIN_WORDS
    kept_text: set[str] = set()
    for script in root.iter("script"):
        sid = script.get("id") or ""
        stype = (script.get("type") or "").lower()
        if sid not in _STATE_SCRIPT_IDS and stype != "application/json":
            continue
        try:
            data = json.loads(script.text or "")
        except ValueError:
            continue
        script_path = tree.getpath(script)
        for json_path, value in _walk_strings(data):
            if value in seen or not _looks_like_prose(value):
                continue
            seen.add(value)
            for block in _body_blocks(value, f"{script_path} {json_path}", base_url):
                plain = _norm(markdown_to_plain(block.text))
                if not plain or plain in kept_text:
                    continue  # the same text stored again (e.g. once per country)
                if check_visible and plain not in visible:
                    continue  # in the data but not shown on this page
                kept_text.add(plain)
                blocks.append(block)
    return blocks


def extract_embedded(root: HtmlElement, base_url: str | None) -> Extraction | None:
    """Return an extraction built from embedded data, or None if there is none."""
    blocks = _from_json_ld(root, base_url)
    if blocks:
        return Extraction(blocks, "embedded")
    blocks = _from_state_scripts(root, base_url)
    if not blocks:
        return None
    # "state": framework data, a fallback that the visible page can outvote (see client).
    return Extraction(blocks, "embedded", extractor="state")
