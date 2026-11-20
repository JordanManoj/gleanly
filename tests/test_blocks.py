from __future__ import annotations

from gleanly.clean import extract_html, markdown_to_plain, parse_html
from gleanly.clean.blocks import extract_blocks, rescue
from gleanly.models import BlockType
from gleanly.quality import compute_quality
from gleanly.quality.crosscheck import cross_check

PROSE = (
    "The committee met on Tuesday to discuss the new budget, which had been delayed for "
    "several weeks because of disagreements about funding for schools and roads."
)


def _text(html: str) -> str:
    ex = extract_html(parse_html(html), None)
    return " ".join(markdown_to_plain(b.text) for b in ex.blocks)


def test_block_extractor_keeps_prose_with_provenance() -> None:
    links = "".join(f'<li><a href="/{i}">Story {i}</a></li>' for i in range(6))
    html = f"<html><body><ul>{links}</ul><p>{PROSE}</p><h2>Budget</h2><p>{PROSE}</p></body></html>"
    root = parse_html(html)
    ex = extract_blocks(root, "http")
    assert ex.extractor == "blocks"
    para = BlockType.PARAGRAPH
    assert [b.type for b in ex.blocks] == [para, BlockType.HEADING, para]
    assert ex.blocks[1].text == "## Budget"
    assert all(b.dom_path and b.dom_path.startswith("/html/body") for b in ex.blocks)
    assert "Story" not in " ".join(b.text for b in ex.blocks)


def test_rescue_only_when_main_extraction_missed_the_page() -> None:
    page = "<html><body>" + "".join(f"<p>{PROSE}</p>" for _ in range(5)) + "</body></html>"
    root = parse_html(page)
    good = extract_html(root, None)
    assert rescue(good, root) is None  # main extractor did fine

    empty = extract_html(parse_html("<html><body></body></html>"), None)
    empty.method = "http"
    rescued = rescue(empty, root)
    assert rescued is not None
    assert rescued.word_count > 100
    assert cross_check(rescued, root).confidence is None  # cannot check itself
    q = compute_quality(rescued, raw_size=len(page))
    assert q.extractor == "blocks"
    assert any("block classifier" in w for w in q.warnings)


def test_text_outside_body_is_found() -> None:
    root = parse_html(f"<html><body></body>{PROSE} {PROSE}</html>")
    assert extract_blocks(root, "http").word_count > 20


def test_large_page_form_is_kept_small_form_is_dropped() -> None:
    article = "".join(f"<p>{PROSE}</p>" for _ in range(4))
    html = (
        "<html><body><form id='Form1'><div id='nav'><a href='/'>Home</a></div>"
        f"<div class='story'>{article}</div></form>"
        "<form><input name='q'><label>Search the site</label></form></body></html>"
    )
    text = _text(html)
    assert "committee met" in text
    assert "Search the site" not in text


def test_post_wrapper_with_author_class_is_not_a_byline() -> None:
    html = (
        "<html><body><div class='hentry post author-admin'><h2>At Dior</h2>"
        f"<div class='entry-content'><p>{PROSE}</p></div></div>"
        "<div class='author'>By Jane Doe</div></body></html>"
    )
    text = _text(html)
    assert "committee met" in text
    assert "Jane Doe" not in text
