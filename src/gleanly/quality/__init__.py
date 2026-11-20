"""Quality signals and the cross-source trust score.

v0 weights are hand-set heuristics. Phase 4 calibrates them against downstream
RAG accuracy on a benchmark, so treat the score as relative, not absolute.
"""

from __future__ import annotations

import math

from gleanly.clean.html import Extraction
from gleanly.models import BlockType, QualityReport
from gleanly.quality.crosscheck import LOW_CONFIDENCE

W_LENGTH = 0.55
W_LINKS = 0.25
W_STRUCTURE = 0.20
# Share of the score given to the extraction cross-check when it is available.
W_CONFIDENCE = 0.35


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_quality(
    extraction: Extraction,
    *,
    raw_size: int,
    status_code: int | None = None,
    language: str | None = None,
    truncated: bool = False,
    js_suspect: bool = False,
    extraction_confidence: float | None = None,
    extraction_support: float | None = None,
    extraction_coverage: float | None = None,
) -> QualityReport:
    words = extraction.word_count
    chars = extraction.content_chars
    link_density = _clip(extraction.link_chars / chars) if chars else 0.0
    text_density = _clip(chars / raw_size) if raw_size else 0.0
    page = extraction.page_chars
    boilerplate = _clip(1 - chars / page) if page and extraction.method != "embedded" else 0.0

    s_length = _clip(math.log1p(words) / math.log1p(400))
    s_links = 1 - _clip((link_density - 0.2) / 0.5)
    types = [b.type for b in extraction.blocks]
    paragraphs = types.count(BlockType.PARAGRAPH)
    s_structure = 0.7 * _clip(paragraphs / 5) + (0.3 if BlockType.HEADING in types else 0.0)

    score = W_LENGTH * s_length + W_LINKS * s_links + W_STRUCTURE * s_structure
    if extraction_confidence is not None:
        score = (1 - W_CONFIDENCE) * score + W_CONFIDENCE * extraction_confidence
    warnings: list[str] = []
    if extraction_confidence is not None and extraction_confidence < LOW_CONFIDENCE and words:
        sup = 1.0 if extraction_support is None else extraction_support
        cov = 1.0 if extraction_coverage is None else extraction_coverage
        if cov < sup:
            why = (
                "an independent check found prose that is not in the extraction, so part of "
                "the main content (e.g. comments or a second column) may be missing."
            )
        else:
            why = (
                "an independent check did not confirm part of the text, so boilerplate may "
                "have leaked in. Blocks with low `support` are the likely culprits."
            )
        warnings.append(f"Low extraction confidence ({extraction_confidence:.2f}): {why}")
    if words < 50:
        warnings.append(f"Very little text extracted ({words} words).")
    if link_density > 0.5:
        warnings.append("Mostly link text: this may be a navigation or index page.")
    if boilerplate > 0.85 and words >= 50:
        warnings.append("The main content is a small part of the page; check the extraction.")
    if js_suspect and extraction.method == "http":
        warnings.append(
            "The page seems to be rendered by JavaScript; install the [browser] extra for "
            "better results."
        )
    if extraction.extractor == "blocks":
        warnings.append(
            "The main extractor found little text, so the block classifier was used instead; "
            "the layout is unusual, so check the result."
        )
    if truncated:
        warnings.append("The response exceeded max_bytes and was truncated.")
        score *= 0.8
    if status_code is not None and not 200 <= status_code < 300:
        warnings.append(f"Non-success HTTP status {status_code}.")
        score *= 0.2
    if words == 0:
        score = 0.0

    return QualityReport(
        score=round(_clip(score), 3),
        word_count=words,
        char_count=chars,
        text_density=round(text_density, 4),
        link_density=round(link_density, 4),
        boilerplate_ratio=round(boilerplate, 4),
        extraction_method=extraction.method,
        extractor=extraction.extractor,
        extraction_confidence=extraction_confidence,
        extraction_support=extraction_support,
        extraction_coverage=extraction_coverage,
        language=language,
        warnings=warnings,
    )


__all__ = ["compute_quality"]
