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
        default=None, description="x0, y0, x1, y1 region on the page or image (later)."
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
    ocr_confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)


AIUse = Literal["allowed", "disallowed", "unclear"]


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
    noai: bool = Field(default=False, description="A 'noai' robots directive was found.")
    license: str | None = Field(default=None, description="Detected license, SPDX-like id.")
    license_url: str | None = None
    pii_detected: bool | None = None
    pii_types: list[str] = Field(default_factory=list)
    ai_use: AIUse = "unclear"
    evidence: list[str] = Field(default_factory=list)


class FetchStep(_Model):
    rung: str = Field(description="robots | tdmrep | http | embedded | browser | file")
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
