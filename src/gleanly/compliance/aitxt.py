"""ai.txt: a site-wide file at ``/ai.txt`` saying which content may be used for AI training.

The format (introduced by Spawning) follows robots.txt: ``User-Agent:`` groups with
``Allow:`` / ``Disallow:`` rules. Rules are either paths (``/blog/``, ``/``) or file-type
patterns (``*.html``, ``*.txt``). A page fetched as HTML is also matched by ``*.html`` /
``*.htm`` rules even when its URL has no extension, since that is what those rules mean.

As with robots.txt, the longest matching rule wins and ``Allow`` wins a tie. No matching
rule means no signal. Like everything in compliance/, this is evidence, not legal advice.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from gleanly.fetch.http import http_get, origin_of

MAX_BYTES = 500_000
# File extensions a document of each content type counts as, for "*.ext" rules.
TYPE_EXTENSIONS = {
    "text/html": ("html", "htm"),
    "application/xhtml+xml": ("html", "htm", "xhtml"),
    "text/plain": ("txt",),
    "text/markdown": ("md", "markdown"),
    "text/x-markdown": ("md", "markdown"),
    "application/pdf": ("pdf",),
}
_EXT_RULE = re.compile(r"^\*\.([A-Za-z0-9]+)$")


@dataclass(frozen=True)
class AiTxtVerdict:
    allowed: bool | None  # None = the file has no rule for this content
    rule: str | None = None  # the deciding line, e.g. "Disallow: *.html"
    agent: str | None = None  # the User-Agent group used

    def describe(self) -> str:
        if self.allowed is None:
            return "ai.txt: no rule matches this content"
        state = "allows" if self.allowed else "disallows"
        return f"ai.txt {state} AI use ({self.rule}, User-Agent: {self.agent})"


@dataclass
class AiTxt:
    groups: dict[str, list[tuple[bool, str]]] = field(default_factory=dict)

    def verdict(self, url: str, content_type: str | None, token: str) -> AiTxtVerdict:
        agent = token.lower() if token.lower() in self.groups else "*"
        rules = self.groups.get(agent)
        if not rules:
            return AiTxtVerdict(None)
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        ctype = (content_type or "").split(";")[0].strip().lower()
        exts = TYPE_EXTENSIONS.get(ctype, ())
        best: tuple[int, bool, str] | None = None
        for allow, pattern in rules:
            if not _matches(pattern, path, exts):
                continue
            key = (len(pattern), allow, pattern)
            if best is None or key[:2] > best[:2]:
                best = key
        if best is None:
            return AiTxtVerdict(None, agent=agent)
        _, allow, pattern = best
        return AiTxtVerdict(allow, f"{'Allow' if allow else 'Disallow'}: {pattern}", agent)


def _matches(pattern: str, path: str, exts: tuple[str, ...]) -> bool:
    ext = _EXT_RULE.match(pattern)
    if ext and ext.group(1).lower() in exts:
        return True  # "*.html" covers any page served as HTML
    if pattern in ("*", "/*"):
        return True
    loc = pattern if pattern.startswith(("/", "*")) else "/" + pattern
    anchored = loc.endswith("$")
    if anchored:
        loc = loc[:-1]
    regex = ".*".join(re.escape(p) for p in loc.split("*")) + ("$" if anchored else "")
    return re.match(regex, path, re.IGNORECASE if ext else 0) is not None


def parse(text: str) -> AiTxt | None:
    """Parse an ai.txt body. None if it has no rules (e.g. an HTML 'not found' page)."""
    result = AiTxt()
    agents: list[str] = []
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name, value = name.strip().lower(), value.strip()
        if name in ("user-agent", "useragent"):
            if in_rules:  # a new group starts
                agents, in_rules = [], False
            agents.append(value.lower())
            for a in agents:
                result.groups.setdefault(a, [])
        elif name in ("allow", "disallow") and value:
            in_rules = True
            for a in agents or ["*"]:
                result.groups.setdefault(a, []).append((name == "allow", value))
    if not any(result.groups.values()):
        return None
    return result


class AiTxtCache:
    """Fetches ``/ai.txt`` once per origin."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._files: dict[str, AiTxt | None] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, url: str) -> AiTxt | None:
        origin = origin_of(url)
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin not in self._files:
                parsed: AiTxt | None = None
                try:
                    resp = await http_get(self._client, f"{origin}/ai.txt", max_bytes=MAX_BYTES)
                    if resp.status_code == 200 and "html" not in resp.content_type:
                        parsed = parse(resp.text())
                except httpx.HTTPError:
                    parsed = None
                self._files[origin] = parsed
            return self._files[origin]


__all__ = ["AiTxt", "AiTxtCache", "AiTxtVerdict", "parse"]
