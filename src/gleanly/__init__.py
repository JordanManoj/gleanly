"""All-in-one text acquisition for AI: URL/file -> clean Markdown with quality,
compliance and provenance metadata.

    >>> from gleanly import load
    >>> doc = load("https://example.com")
    >>> doc.markdown, doc.quality.score, doc.compliance.ai_use
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
)

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
    "UnsupportedSourceError",
    "__version__",
    "aload",
    "load",
]
