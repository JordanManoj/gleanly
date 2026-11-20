from __future__ import annotations

from gleanly.clean import extract_html, parse_html
from gleanly.clean.html import Extraction, RawBlock
from gleanly.models import BlockType
from gleanly.quality import compute_quality
from gleanly.quality.crosscheck import LOW_CONFIDENCE, cross_check, reference_text

from .conftest import fixture_text

PROSE = (
    "The committee met on Tuesday to discuss the new budget, which had been delayed for "
    "several weeks because of disagreements about funding for schools and roads."
)


def _page(paragraphs: int = 6, extra: str = "") -> str:
    body = "".join(f"<p>{PROSE} Paragraph {i}.</p>" for i in range(paragraphs))
    return f"<html><body><article>{body}</article>{extra}</body></html>"


def test_reference_keeps_prose_and_drops_link_lists() -> None:
    links = "".join(f'<li><a href="/s{i}">Related story number {i}</a></li>' for i in range(8))
    root = parse_html(_page(extra=f"<div><ul>{links}</ul></div>"))
    ref = reference_text(root)
    assert "committee met on Tuesday" in ref
    assert "Related story" not in ref


def test_clean_article_gets_full_confidence() -> None:
    root = parse_html(fixture_text("article.html"))
    extraction = extract_html(root, "https://example.com/a")
    check = cross_check(extraction, root)
    assert check.confidence is not None
    assert check.confidence >= 0.9
    assert len(check.block_support) == len(extraction.blocks)


def test_leaked_boilerplate_block_gets_low_support() -> None:
    root = parse_html(_page())
    leaked = "Subscribe Login Register Contact Advertise Careers Privacy Terms Sitemap Help"
    blocks = [RawBlock(BlockType.PARAGRAPH, f"{PROSE} Paragraph {i}.", None) for i in range(6)]
    blocks.append(RawBlock(BlockType.PARAGRAPH, leaked, None))
    check = cross_check(Extraction(blocks, "http"), root)
    assert check.block_support[0] == 1.0
    assert check.block_support[-1] == 0.0
    assert check.confidence is not None
    assert check.confidence < 1.0


def test_too_little_reference_text_means_unknown() -> None:
    root = parse_html("<html><body><div id='root'></div><p>Loading...</p></body></html>")
    blocks = [RawBlock(BlockType.PARAGRAPH, PROSE, None)]
    check = cross_check(Extraction(blocks, "embedded"), root)
    assert check.confidence is None
    assert check.block_support == [None]


def test_no_root_means_unknown() -> None:
    check = cross_check(Extraction([RawBlock(BlockType.PARAGRAPH, PROSE, None)], "file"), None)
    assert check.confidence is None


def test_low_confidence_lowers_score_and_warns() -> None:
    blocks = [RawBlock(BlockType.PARAGRAPH, PROSE, None) for _ in range(8)]
    ex = Extraction(blocks, "http")
    ex.page_chars = ex.content_chars * 2
    high = compute_quality(ex, raw_size=20_000, extraction_confidence=1.0)
    low = compute_quality(ex, raw_size=20_000, extraction_confidence=LOW_CONFIDENCE - 0.3)
    assert high.extraction_confidence == 1.0
    assert low.score < high.score
    assert any("Low extraction confidence" in w for w in low.warnings)
    assert not any("Low extraction confidence" in w for w in high.warnings)


def test_missed_prose_lowers_coverage_not_support() -> None:
    # The page has twelve paragraphs of prose; the extraction kept only the first three.
    root = parse_html(_page(paragraphs=12))
    blocks = [RawBlock(BlockType.PARAGRAPH, f"{PROSE} Paragraph {i}.", None) for i in range(3)]
    check = cross_check(Extraction(blocks, "http"), root)
    assert check.support == 1.0
    assert check.coverage is not None
    assert check.coverage < 0.5
    assert check.confidence is not None
    assert check.confidence < LOW_CONFIDENCE


def test_warning_names_the_weak_side() -> None:
    blocks = [RawBlock(BlockType.PARAGRAPH, PROSE, None) for _ in range(8)]
    ex = Extraction(blocks, "http")
    missing = compute_quality(
        ex,
        raw_size=20_000,
        extraction_confidence=0.3,
        extraction_support=1.0,
        extraction_coverage=0.3,
    )
    leaked = compute_quality(
        ex,
        raw_size=20_000,
        extraction_confidence=0.3,
        extraction_support=0.3,
        extraction_coverage=1.0,
    )
    assert any("may be missing" in w for w in missing.warnings)
    assert any("leaked" in w for w in leaked.warnings)
    assert missing.extraction_coverage == 0.3
