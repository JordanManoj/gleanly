"""Combine individual signals into a ComplianceInfo with an AI-use verdict."""

from __future__ import annotations

from lxml.html import HtmlElement

from gleanly.compliance.license import LicenseInfo, is_permissive
from gleanly.compliance.tdmrep import TdmSignal, most_specific
from gleanly.fetch.robots import RobotsVerdict
from gleanly.models import ComplianceInfo


def detect_noai(headers: dict[str, str], root: HtmlElement | None) -> list[str]:
    """Return evidence strings for 'noai' / 'noimageai' directives."""
    evidence: list[str] = []
    tag = headers.get("x-robots-tag", "").lower()
    if "noai" in tag or "noimageai" in tag:
        evidence.append(f"X-Robots-Tag header: {headers['x-robots-tag']}")
    if root is not None:
        for m in root.iter("meta"):
            name = (m.get("name") or "").lower()
            content = (m.get("content") or "").lower()
            if name in ("robots", "googlebot") and ("noai" in content or "noimageai" in content):
                evidence.append(f'<meta name="{name}" content="{content}">')
    return evidence


def assess(
    *,
    robots: RobotsVerdict | None,
    respect_robots: bool = True,
    tdm_signals: list[TdmSignal] | None = None,
    noai_evidence: list[str] | None = None,
    license_info: LicenseInfo | None = None,
    pii_types: list[str] | None = None,
    local: bool = False,
) -> ComplianceInfo:
    evidence: list[str] = []
    negative: list[str] = []
    positive: list[str] = []

    if local:
        evidence.append("Local file: no robots.txt or HTTP signals available.")
    if robots is not None:
        evidence.append(f"robots.txt ({robots.status}): {robots.detail}")
        if robots.allowed is False:
            if not respect_robots:
                evidence.append("robots.txt was ignored at the caller's request.")
            negative.append("robots.txt disallows fetching this URL")
        if robots.ai_crawlers_blocked:
            names = ", ".join(robots.ai_crawlers_blocked)
            evidence.append(f"robots.txt blocks AI crawlers but not generic ones: {names}")
            negative.append("robots.txt opts out of AI crawlers")

    signals = tdm_signals or []
    for s in signals:
        evidence.append(s.describe())
    tdm = most_specific(signals)
    if tdm is not None and tdm.reserved is True:
        negative.append("TDM rights are reserved (TDMRep)")
    elif tdm is not None and tdm.reserved is False:
        positive.append("TDMRep explicitly does not reserve TDM rights")

    noai = bool(noai_evidence)
    for e in noai_evidence or []:
        evidence.append(f"noai directive: {e}")
    if noai:
        negative.append("a noai directive is present")

    if license_info is not None:
        evidence.append(f"License {license_info.license} detected via {license_info.evidence}")
        if is_permissive(license_info.license):
            positive.append(f"permissive license {license_info.license}")
        else:
            evidence.append(
                f"License {license_info.license} restricts reuse (e.g. NC/ND); check its terms."
            )

    if pii_types:
        evidence.append(f"Possible personal data in text: {', '.join(pii_types)}")

    if negative:
        ai_use = "disallowed"
        evidence.append("Verdict disallowed: " + "; ".join(negative) + ".")
    elif positive:
        ai_use = "allowed"
        evidence.append("Verdict allowed: " + "; ".join(positive) + ".")
    else:
        ai_use = "unclear"
        evidence.append("Verdict unclear: no explicit permission or reservation found.")

    return ComplianceInfo(
        robots_allowed=robots.allowed if robots is not None else None,
        ai_crawlers_blocked=list(robots.ai_crawlers_blocked) if robots is not None else [],
        tdm_reserved=tdm.reserved if tdm is not None else None,
        tdm_policy=tdm.policy if tdm is not None else None,
        noai=noai,
        license=license_info.license if license_info else None,
        license_url=license_info.url if license_info else None,
        pii_detected=bool(pii_types) if pii_types is not None else None,
        pii_types=pii_types or [],
        ai_use=ai_use,
        evidence=evidence,
    )
