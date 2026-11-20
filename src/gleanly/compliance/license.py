"""Detect a content license declared on a page and map it to an SPDX-like id."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from lxml.html import HtmlElement

from gleanly.clean.metadata import json_ld_objects

_CC = re.compile(
    r"creativecommons\.org/(licenses|publicdomain)/([a-z+-]+)(?:/(\d(?:\.\d)?))?", re.I
)
_KNOWN = {
    "opensource.org/licenses/mit": "MIT",
    "apache.org/licenses/license-2.0": "Apache-2.0",
    "opendatacommons.org/licenses/odbl": "ODbL-1.0",
    "opendatacommons.org/licenses/by": "ODC-By-1.0",
    "opendatacommons.org/licenses/pddl": "PDDL-1.0",
    "gnu.org/licenses/fdl": "GFDL",
    "gnu.org/licenses/gpl": "GPL",
}
# Licenses that clearly permit reuse, including for AI training (attribution may apply).
_PERMISSIVE_EXACT = {"CC0-1.0", "public-domain", "MIT", "Apache-2.0", "ODC-By-1.0", "PDDL-1.0"}


@dataclass(frozen=True)
class LicenseInfo:
    license: str
    url: str | None
    evidence: str


def license_from_url(url: str) -> str | None:
    if m := _CC.search(url):
        kind, code, version = m.group(1).lower(), m.group(2).lower(), m.group(3)
        if kind == "publicdomain":
            return "CC0-1.0" if code == "zero" else "public-domain"
        ident = "CC-" + code.upper()
        return f"{ident}-{version}" if version else ident
    lowered = url.lower()
    for needle, spdx in _KNOWN.items():
        if needle in lowered:
            return spdx
    return None


def is_permissive(license_id: str) -> bool:
    if license_id in _PERMISSIVE_EXACT:
        return True
    if license_id.startswith("CC-BY"):
        return "-NC" not in license_id and "-ND" not in license_id
    return False


def detect_license(
    root: HtmlElement, json_ld: list[tuple[str, Any]], base_url: str | None
) -> LicenseInfo | None:
    def absolute(href: str) -> str:
        return urljoin(base_url, href) if base_url else href

    # 1. <link rel="license"> / <a rel="license">
    for el in root.iter("link", "a"):
        if "license" in (el.get("rel") or "").lower().split() and el.get("href"):
            href = absolute(el.get("href") or "")
            lic = license_from_url(href)
            if lic:
                return LicenseInfo(lic, href, f'<{el.tag} rel="license" href="{href}">')
    # 2. <meta name="license" | dc.rights | dcterms.license>
    for m in root.iter("meta"):
        name = (m.get("name") or m.get("property") or "").lower()
        if name in ("license", "dc.rights", "dcterms.license", "dcterms.rights"):
            content = (m.get("content") or "").strip()
            lic = license_from_url(content)
            if lic:
                return LicenseInfo(lic, content, f'<meta name="{name}" content="{content}">')
    # 3. JSON-LD "license"
    for _, data in json_ld:
        for obj in json_ld_objects(data):
            value = obj.get("license")
            if isinstance(value, dict):
                value = value.get("url") or value.get("@id")
            if isinstance(value, str) and (lic := license_from_url(value)):
                return LicenseInfo(lic, value, f'JSON-LD "license": {value}')
    # 4. Any link to a Creative Commons license (typical in footers)
    for a in root.iter("a"):
        href = a.get("href") or ""
        if "creativecommons.org/" in href and (lic := license_from_url(href)):
            return LicenseInfo(lic, absolute(href), f"link to {href}")
    return None
