"""All-in-one text acquisition for AI: URL/file -> clean Markdown with quality,
compliance and provenance metadata; web search with the same on every result.

    >>> from gleanly import load, search
    >>> doc = load("https://example.com")
    >>> doc.markdown, doc.quality.score, doc.compliance.ai_use
    >>> results = search("tide pools", backends=["wikipedia"])
"""

from gleanly.__about__ import __version__
from gleanly.client import Client
from gleanly.config import LoadOptions
from gleanly.errors import (
    AcquisitionError,
    BrowserUnavailable,
    FetchError,
    RobotsDisallowed,
    UnsupportedSourceError,
)
from gleanly.loader import aload, load
from gleanly.models import (
    Block,
    BlockType,
    ComplianceInfo,
    Document,
    FetchStep,
    FetchTrace,
    Metadata,
    Provenance,
    QualityReport,
    SearchHit,
    SearchResponse,
    SearchResult,
)
from gleanly.search import asearch, search

__all__ = [
    "AcquisitionError",
    "Block",
    "BlockType",
    "BrowserUnavailable",
    "Client",
    "ComplianceInfo",
    "Document",
    "FetchError",
    "FetchStep",
    "FetchTrace",
    "LoadOptions",
    "Metadata",
    "Provenance",
    "QualityReport",
    "RobotsDisallowed",
    "SearchHit",
    "SearchResponse",
    "SearchResult",
    "UnsupportedSourceError",
    "__version__",
    "aload",
    "asearch",
    "load",
    "search",
]
