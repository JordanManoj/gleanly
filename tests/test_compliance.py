from __future__ import annotations

import pytest

from gleanly.clean import iter_json_ld, parse_html
from gleanly.compliance import aitxt, assess, detect_license, detect_noai, detect_pii, is_permissive
from gleanly.compliance.license import LicenseInfo, license_from_url
from gleanly.compliance.tdmrep import TdmSignal, from_headers, from_html, match_rules, most_specific
from gleanly.fetch.robots import RobotsVerdict

from .conftest import fixture_text

# ---------------------------------------------------------------- license


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://creativecommons.org/licenses/by/4.0/", "CC-BY-4.0"),
        ("https://creativecommons.org/licenses/by-nc-sa/3.0/deed.en", "CC-BY-NC-SA-3.0"),
        ("https://creativecommons.org/publicdomain/zero/1.0/", "CC0-1.0"),
        ("https://creativecommons.org/publicdomain/mark/1.0/", "public-domain"),
        ("https://opensource.org/licenses/MIT", "MIT"),
        ("https://www.apache.org/licenses/LICENSE-2.0", "Apache-2.0"),
        ("https://example.com/terms", None),
    ],
)
def test_license_from_url(url: str, expected: str | None) -> None:
    assert license_from_url(url) == expected


@pytest.mark.parametrize(
    ("license_id", "permissive"),
    [
        ("CC-BY-4.0", True),
        ("CC-BY-SA-4.0", True),
        ("CC-BY-NC-4.0", False),
        ("CC-BY-ND-4.0", False),
        ("CC0-1.0", True),
        ("MIT", True),
        ("GPL", False),
    ],
)
def test_is_permissive(license_id: str, permissive: bool) -> None:
    assert is_permissive(license_id) is permissive


def test_detect_license_sources() -> None:
    root = parse_html(fixture_text("article.html"))
    info = detect_license(root, iter_json_ld(root), "https://fieldnotes.example/")
    assert info is not None
    assert info.license == "CC-BY-4.0"
    assert "rel=" in info.evidence

    root = parse_html(fixture_text("jsonld_article.html"))
    info = detect_license(root, iter_json_ld(root), None)
    assert info is not None
    assert info.license == "CC-BY-NC-4.0"
    assert "JSON-LD" in info.evidence

    root = parse_html('<footer><a href="https://creativecommons.org/licenses/by-sa/4.0/">x</a>')
    info = detect_license(root, [], None)
    assert info is not None
    assert info.license == "CC-BY-SA-4.0"

    assert detect_license(parse_html("<p>no license</p>"), [], None) is None


# ---------------------------------------------------------------- PII


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Write to jane.doe@example.com for details.", ["email"]),
        ("Call +44 20 7946 0958 today.", ["phone"]),
        ("Card 4111 1111 1111 1111 on file.", ["credit_card"]),
        ("IBAN GB82 WEST 1234 5698 7654 32 please.", ["iban"]),
        ("Published 2024-05-01, version 3.12.1, 1,234 visitors.", []),
        ("See [the docs](mailto:help@example.com) for more.", []),
        ("Order number 1234 5678 9012 3456 is invalid Luhn.", []),
    ],
)
def test_detect_pii(text: str, expected: list[str]) -> None:
    assert detect_pii(text) == expected


# ---------------------------------------------------------------- TDMRep


def test_tdmrep_header_and_meta() -> None:
    sig = from_headers({"tdm-reservation": "1", "tdm-policy": "https://p.example/policy"})
    assert sig == TdmSignal(True, "https://p.example/policy", "header")
    assert from_headers({}) is None

    meta = from_html(parse_html(fixture_text("jsonld_article.html")))
    assert meta is not None
    assert meta.reserved is True
    assert meta.policy == "https://publisher.example/tdm-policy.json"
    assert from_html(parse_html("<p>x</p>")) is None


def test_tdmrep_well_known_rules() -> None:
    rules = [
        {"location": "/public/*", "tdm-reservation": 0},
        {"location": "/news/*.html$", "tdm-reservation": 1, "tdm-policy": "https://p/x"},
        {"location": "/", "tdm-reservation": 1},
    ]
    public = match_rules(rules, "https://a.example/public/doc")
    assert public is not None
    assert public.reserved is False
    news = match_rules(rules, "https://a.example/news/today.html")
    assert news is not None
    assert news.policy == "https://p/x"
    # "$" anchors the end, so a query-less match falls through to the catch-all rule.
    other = match_rules(rules, "https://a.example/news/today.html.bak")
    assert other is not None
    assert other.policy is None
    assert match_rules("not a list", "https://a.example/") is None


def test_most_specific_signal_wins() -> None:
    wk = TdmSignal(True, None, "well-known")
    meta = TdmSignal(False, None, "meta")
    assert most_specific([meta, wk]) is meta
    assert most_specific([]) is None


# ---------------------------------------------------------------- noai + verdict


def test_detect_noai() -> None:
    assert detect_noai({"x-robots-tag": "noai, noimageai"}, None)
    root = parse_html(fixture_text("jsonld_article.html"))
    assert detect_noai({}, root) == ['<meta name="robots" content="index, follow, noai">']
    assert detect_noai({}, parse_html("<p>x</p>")) == []


def _robots(allowed: bool | None = True, blocked: tuple[str, ...] = ()) -> RobotsVerdict:
    return RobotsVerdict(allowed, "fetched", "detail", ai_crawlers_blocked=blocked)


def test_verdict_unclear_without_signals() -> None:
    info = assess(robots=_robots())
    assert info.ai_use == "unclear"
    assert info.robots_allowed is True
    assert info.pii_detected is None


def test_verdict_allowed_with_permissive_license() -> None:
    info = assess(robots=_robots(), license_info=LicenseInfo("CC-BY-4.0", "u", "e"))
    assert info.ai_use == "allowed"
    assert info.license == "CC-BY-4.0"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"robots": _robots(blocked=("GPTBot", "CCBot"))},
        {"robots": _robots(), "tdm_signals": [TdmSignal(True, None, "header")]},
        {"robots": _robots(), "noai_evidence": ["X-Robots-Tag: noai"]},
        {"robots": _robots(False), "respect_robots": False},
    ],
)
def test_negative_signals_beat_permissive_license(kwargs: dict[str, object]) -> None:
    info = assess(license_info=LicenseInfo("CC0-1.0", None, "e"), **kwargs)  # type: ignore[arg-type]
    assert info.ai_use == "disallowed"
    assert info.evidence[-1].startswith("Verdict disallowed")


def test_tdm_not_reserved_is_positive_and_pii_reported() -> None:
    info = assess(
        robots=None,
        tdm_signals=[TdmSignal(False, None, "well-known")],
        pii_types=["email"],
        local=True,
    )
    assert info.ai_use == "allowed"
    assert info.tdm_reserved is False
    assert info.pii_detected is True
    assert info.pii_types == ["email"]
    assert info.robots_allowed is None
    assert any("Local file" in e for e in info.evidence)


# ------------------------------------------------------------------ ai.txt
SPAWNING = """# Spawning AI
# Prevent datasets from using the following file types

User-Agent: *
Disallow: *.jpg
Disallow: *.png
Allow: *.html
Allow: *.txt

User-Agent: gleanly
Disallow: /private/
"""


def test_ai_txt_file_type_rules_match_html_pages_without_extension() -> None:
    ai = aitxt.parse(SPAWNING)
    assert ai is not None
    v = ai.verdict("https://ex.com/blog/post", "text/html; charset=utf-8", "otherbot")
    assert v.allowed is True
    assert v.rule == "Allow: *.html"
    assert ai.verdict("https://ex.com/cat.jpg", "image/jpeg", "otherbot").allowed is False


def test_ai_txt_own_group_and_longest_rule() -> None:
    ai = aitxt.parse(SPAWNING)
    assert ai is not None
    # The gleanly group replaces "*": only /private/ is ruled on.
    assert ai.verdict("https://ex.com/private/x", "text/html", "gleanly").allowed is False
    assert ai.verdict("https://ex.com/blog", "text/html", "gleanly").allowed is None
    site = aitxt.parse("User-Agent: *\nDisallow: /\nAllow: /open/\n")
    assert site is not None
    assert site.verdict("https://ex.com/open/a", "text/html", "x").allowed is True
    assert site.verdict("https://ex.com/closed", "text/html", "x").allowed is False


@pytest.mark.parametrize("body", ["", "<html><body>Not found</body></html>", "# only comments"])
def test_ai_txt_without_rules_is_no_signal(body: str) -> None:
    assert aitxt.parse(body) is None


def test_ai_txt_in_verdict() -> None:
    blocked = assess(robots=None, ai_txt=aitxt.AiTxtVerdict(False, "Disallow: /", "*"))
    assert blocked.ai_use == "disallowed"
    assert blocked.ai_txt_allowed is False
    allowed = assess(robots=None, ai_txt=aitxt.AiTxtVerdict(True, "Allow: *.html", "*"))
    assert allowed.ai_use == "allowed"


@pytest.mark.parametrize(
    ("lic", "expected"),
    [
        ("CC-BY-4.0", ["Attribution required"]),
        ("CC-BY-SA-4.0", ["Attribution required", "Share-alike"]),
        ("CC-BY-NC-ND-4.0", ["Attribution required", "Non-commercial", "No derivatives"]),
        ("MIT", ["Keep the copyright"]),
        ("CC0-1.0", []),
    ],
)
def test_license_conditions(lic: str, expected: list[str]) -> None:
    from gleanly.compliance import license_conditions

    got = license_conditions(lic)
    assert len(got) == len(expected)
    for g, e in zip(got, expected, strict=True):
        assert g.startswith(e)


def test_allowed_verdict_carries_conditions_and_disclaimer() -> None:
    info = assess(
        robots=None,
        license_info=LicenseInfo(
            "CC-BY-SA-4.0", "https://creativecommons.org/licenses/by-sa/4.0/", "x"
        ),
        pii_types=["email"],
    )
    assert info.ai_use == "allowed"
    assert any(c.startswith("Attribution required") for c in info.conditions)
    assert any(c.startswith("Share-alike") for c in info.conditions)
    assert any("GDPR" in c for c in info.conditions)
    assert "not legal advice" in info.disclaimer
