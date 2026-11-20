"""TDMRep (W3C Community Group): text-and-data-mining reservation signals.

Three places are checked, from most general to most specific:
``/.well-known/tdmrep.json`` < ``tdm-reservation`` HTTP header < HTML ``<meta>``.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from lxml.html import HtmlElement

from gleanly.fetch.http import http_get, origin_of

_PRIORITY = {"well-known": 0, "header": 1, "meta": 2}


@dataclass(frozen=True)
class TdmSignal:
    reserved: bool | None
    policy: str | None
    source: str  # "well-known" | "header" | "meta"

    def describe(self) -> str:
        state = {True: "reserved (1)", False: "not reserved (0)", None: "unspecified"}
        text = f"TDMRep {self.source}: tdm-reservation {state[self.reserved]}"
        return f"{text}, policy {self.policy}" if self.policy else text


def _parse_reservation(value: object) -> bool | None:
    s = str(value).strip()
    return True if s == "1" else False if s == "0" else None


def from_headers(headers: dict[str, str]) -> TdmSignal | None:
    if "tdm-reservation" not in headers:
        return None
    return TdmSignal(
        _parse_reservation(headers["tdm-reservation"]), headers.get("tdm-policy"), "header"
    )


def from_html(root: HtmlElement) -> TdmSignal | None:
    values: dict[str, str] = {}
    for m in root.iter("meta"):
        name = (m.get("name") or "").strip().lower()
        if name in ("tdm-reservation", "tdm-policy"):
            values.setdefault(name, (m.get("content") or "").strip())
    if "tdm-reservation" not in values:
        return None
    return TdmSignal(
        _parse_reservation(values["tdm-reservation"]), values.get("tdm-policy") or None, "meta"
    )


def _location_regex(location: str) -> re.Pattern[str]:
    loc = location.strip() or "/"
    anchored = loc.endswith("$")
    if anchored:
        loc = loc[:-1]
    if not loc.startswith("/"):
        loc = "/" + loc
    pattern = ".*".join(re.escape(part) for part in loc.split("*"))
    return re.compile(pattern + ("$" if anchored else ""))


def match_rules(rules: object, url: str) -> TdmSignal | None:
    """Return the signal of the first rule whose location matches the URL's path."""
    if not isinstance(rules, list):
        return None
    parts = urlsplit(url)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    for rule in rules:
        if not isinstance(rule, dict) or "location" not in rule:
            continue
        if _location_regex(str(rule["location"])).match(path):
            policy = rule.get("tdm-policy")
            return TdmSignal(
                _parse_reservation(rule.get("tdm-reservation")),
                str(policy) if policy else None,
                "well-known",
            )
    return None


class TdmRepCache:
    """Fetches ``/.well-known/tdmrep.json`` once per origin."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._rules: dict[str, object] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _rules_for(self, origin: str) -> object:
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin not in self._rules:
                rules: object = None
                try:
                    resp = await http_get(
                        self._client, f"{origin}/.well-known/tdmrep.json", max_bytes=500_000
                    )
                    if resp.status_code == 200:
                        rules = json.loads(resp.text())
                except (httpx.HTTPError, ValueError):
                    rules = None
                self._rules[origin] = rules
            return self._rules[origin]

    async def lookup(self, url: str) -> TdmSignal | None:
        return match_rules(await self._rules_for(origin_of(url)), url)


def most_specific(signals: list[TdmSignal]) -> TdmSignal | None:
    return max(signals, key=lambda s: _PRIORITY.get(s.source, -1), default=None)
