"""Public, typed output models.

Every source type (web page, PDF, OCR'd image) produces the same :class:`Document`,
so quality, compliance and provenance are comparable across sources.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CODE = "code"
    QUOTE = "quote"
    IMAGE = "image"


class Provenance(_Model):
    """Where a block came from, precisely enough to point back at it."""

    source: str = Field(description="URL or file URI the block was extracted from.")
    kind: Literal["html", "embedded", "text", "pdf", "image"] = "html"
    dom_path: str | None = Field(
        default=None,
        description="XPath of the source element (HTML), optionally followed by a JSON path "
        "for data embedded in a <script> tag.",
    )
    page: int | None = Field(default=None, description="1-based page number (PDF, later).")
    bbox: tuple[float, float, float, float] | None = Field(
        default=None,
        description="x0, top, x1, bottom of the block on the page: PDF points or image pixels, "
        "origin at the top-left.",
    )
    char_start: int = Field(description="Start offset of the block inside Document.markdown.")
    char_end: int = Field(description="End offset (exclusive) inside Document.markdown.")


class Block(_Model):
    text: str = Field(description="Markdown for this block.")
    type: BlockType
    level: int | None = Field(default=None, description="Heading level 1-6 for headings.")
    support: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Share of this block's words that an independent second extractor also "
        "kept as main content. Low values point at leaked boilerplate. None = not checked.",
    )
    role: Literal["main", "comment"] = Field(
        default="main",
        description="'comment' for reader comments (only with include_comments=True).",
    )
    provenance: Provenance


class ProductInfo(_Model):
    """A product described on the page (from schema.org JSON-LD), for shop pages."""

    name: str | None = None
    brand: str | None = None
    price: float | None = Field(default=None, description="Lowest offer price found.")
    price_max: float | None = Field(default=None, description="Highest price, when offers differ.")
    currency: str | None = None
    availability: str | None = Field(default=None, description='schema.org value, e.g. "InStock".')
    color: str | None = None
    sizes: list[str] = Field(default_factory=list)
    available_sizes: list[str] = Field(default_factory=list)
    sku: str | None = None
    mpn: str | None = None
    gtin: str | None = None
    rating: float | None = None
    review_count: int | None = None
    description: str | None = None


class Metadata(_Model):
    title: str | None = None
    description: str | None = None
    language: str | None = None
    canonical_url: str | None = None
    author: str | None = None
    published_at: str | None = None
    modified_at: str | None = None
    site_name: str | None = None
    image: str | None = None
    content_type: str | None = None
    status_code: int | None = None
    structured_data: list[Any] = Field(
        default_factory=list, description="Parsed JSON-LD objects found on the page."
    )
    product: ProductInfo | None = Field(
        default=None, description="The main product, when the page describes one (shop pages)."
    )


class QualityReport(_Model):
    """Comparable quality signals plus a single score in [0, 1].

    v0: heuristic weights, not yet calibrated against downstream RAG accuracy.
    """

    score: float = Field(ge=0.0, le=1.0)
    word_count: int = 0
    char_count: int = 0
    text_density: float = Field(0.0, description="Extracted text chars / raw bytes.")
    link_density: float = Field(0.0, description="Share of extracted text that is link text.")
    boilerplate_ratio: float = Field(
        0.0, description="Share of the page's visible text that was discarded as boilerplate."
    )
    extraction_method: str = Field(description="Ladder rung that produced the text.")
    extractor: str = Field(
        default="main",
        description="Content extractor that produced the text: 'main' (container scoring) or "
        "'blocks' (block classifier, used when the main extractor missed most of the page).",
    )
    extraction_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="How likely the extraction is complete and clean, from a cross-check "
        "against an independent second extractor: support x sqrt(coverage). None = the page had "
        "too little text to check.",
    )
    extraction_support: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Share of the extracted words the second extractor also kept "
        "(low = boilerplate may have leaked in).",
    )
    extraction_coverage: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Share of the second extractor's content found in the extraction "
        "(low = part of the main content may be missing).",
    )
    language: str | None = None
    ocr_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Tesseract's mean word confidence over OCR'd text (length-weighted). "
        "None = no OCR was used.",
    )
    warnings: list[str] = Field(default_factory=list)


AIUse = Literal["allowed", "disallowed", "unclear"]
COMPLIANCE_DISCLAIMER = (
    "Evidence gathered automatically from the source's signals (robots.txt, TDMRep, "
    "ai.txt, noai, license). It is not legal advice: check the source's terms and the law "
    "that applies to you before using the content, especially for AI training."
)


class ComplianceInfo(_Model):
    """Signals about whether the content may be used, especially for AI.

    This is evidence collection, not legal advice.
    """

    robots_allowed: bool | None = Field(
        default=None, description="Whether robots.txt allows this library to fetch the URL."
    )
    ai_crawlers_blocked: list[str] = Field(
        default_factory=list,
        description="Well-known AI-training crawlers that robots.txt blocks for this URL while "
        "allowing generic crawlers (a strong opt-out signal).",
    )
    tdm_reserved: bool | None = Field(
        default=None, description="TDMRep text-and-data-mining reservation (None = no signal)."
    )
    tdm_policy: str | None = None
    ai_txt_allowed: bool | None = Field(
        default=None,
        description="What the site's /ai.txt says about AI use of this content "
        "(None = no ai.txt or no matching rule).",
    )
    noai: bool = Field(default=False, description="A 'noai' robots directive was found.")
    license: str | None = Field(default=None, description="Detected license, SPDX-like id.")
    license_url: str | None = None
    pii_detected: bool | None = None
    pii_types: list[str] = Field(default_factory=list)
    ai_use: AIUse = Field(
        default="unclear",
        description="allowed / disallowed / unclear, from the signals above. 'allowed' can "
        "still come with conditions (see `conditions`).",
    )
    conditions: list[str] = Field(
        default_factory=list,
        description="Obligations implied by the evidence, e.g. attribution required "
        "(CC-BY) or data-protection law applies (personal data found).",
    )
    evidence: list[str] = Field(default_factory=list)
    disclaimer: str = Field(
        default=COMPLIANCE_DISCLAIMER,
        description="This report is evidence gathered automatically, not legal advice.",
    )


class FetchStep(_Model):
    rung: str = Field(
        description="robots | tdmrep | ai.txt | http | embedded | browser | file | pdf | ocr "
        "| text-check"
    )
    url: str | None = None
    ok: bool
    status_code: int | None = None
    duration_ms: float | None = None
    detail: str | None = None


class FetchTrace(_Model):
    steps: list[FetchStep] = Field(default_factory=list)
    final_url: str | None = None
    final_rung: str | None = None
    failure_reason: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Document(_Model):
    source: str = Field(description="What the caller asked for (URL or path).")
    url: str | None = Field(default=None, description="Final URL after redirects.")
    markdown: str
    blocks: list[Block] = Field(default_factory=list)
    metadata: Metadata = Field(default_factory=Metadata)
    quality: QualityReport
    compliance: ComplianceInfo = Field(default_factory=ComplianceInfo)
    fetch_trace: FetchTrace = Field(default_factory=FetchTrace)
    fetched_at: datetime = Field(default_factory=_now)


# ----------------------------------------------------------------------------- search
class SearchHit(_Model):
    """One result as the search engines returned it, before fetching."""

    url: str
    title: str = ""
    snippet: str = ""
    engines: list[str] = Field(default_factory=list, description="Backends that returned this URL.")
    ranks: dict[str, int] = Field(
        default_factory=dict, description="1-based rank of this URL in each backend's list."
    )
    fused_score: float = Field(
        default=0.0, description="Reciprocal-rank-fusion score across backends (higher = better)."
    )


class SearchResult(_Model):
    """A search hit, fetched and cleaned like any other source."""

    hit: SearchHit
    document: Document | None = Field(
        default=None, description="The fetched page (Markdown, quality, compliance, provenance)."
    )
    error: str | None = Field(default=None, description="Why the page could not be fetched.")
    relevance: float | None = Field(
        default=None, ge=0.0, le=1.0, description="How well the page text matches the query."
    )
    score: float = Field(
        default=0.0, description="Final ranking score: relevance and fusion, weighted by trust."
    )


class ClaimSource(_Model):
    """Where a fact was found: the page, the block and the exact span in its Markdown."""

    url: str
    block_index: int
    char_start: int
    char_end: int
    quote: str = Field(description="The sentence containing the fact.")


class FactValue(_Model):
    value: str = Field(description="The value as written, e.g. '1997' or '8,849 m'.")
    sources: list[ClaimSource] = Field(default_factory=list)


class FactGroup(_Model):
    """Facts from different sources about the same thing (matched by their context)."""

    topic: str = Field(description="Context words the sources share.")
    kind: str = Field(description="year, percent, number, currency:$, unit:km, ...")
    values: list[FactValue] = Field(
        default_factory=list, description="One entry per distinct value, most-cited first."
    )


class AgreementReport(_Model):
    """Cross-source agreement on numeric and date facts (v0 heuristic; see search/agreement.py)."""

    conflicts: list[FactGroup] = Field(
        default_factory=list, description="Sources give different values for the same thing."
    )
    corroborated: list[FactGroup] = Field(
        default_factory=list, description="Two or more sources give the same value."
    )


class SearchResponse(_Model):
    query: str
    results: list[SearchResult] = Field(default_factory=list)
    backends: list[str] = Field(default_factory=list, description="Backends that answered.")
    agreement: AgreementReport | None = Field(
        default=None,
        description="Where the fetched sources agree or contradict each other (numbers, dates).",
    )
    warnings: list[str] = Field(default_factory=list)
    searched_at: datetime = Field(default_factory=_now)
