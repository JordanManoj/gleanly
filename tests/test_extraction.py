from __future__ import annotations

from gleanly.clean import extract_html, extract_metadata, iter_json_ld, parse_html
from gleanly.client import assemble
from gleanly.models import BlockType

from .conftest import fixture_text


def _article():
    root = parse_html(fixture_text("article.html"))
    return root, extract_html(root, "https://fieldnotes.example/guides/tide-pools", method="http")


def test_main_content_drops_boilerplate() -> None:
    _, ex = _article()
    md, _ = assemble(ex.blocks, "u")
    assert md.startswith("# Understanding Tide Pools")
    for junk in ("cookies", "About", "Another article", "editors@example.org", "Copyright"):
        assert junk not in md


def test_structure_is_preserved() -> None:
    _, ex = _article()
    md, _ = assemble(ex.blocks, "u")
    assert "## Zones of the shore" in md
    assert "- The **spray zone** is wetted only by waves." in md
    assert "- The *high intertidal* zone" in md
    assert "| Zone | Max temp (C) |\n| --- | --- |\n| Spray | 34 |" in md
    assert "```python\ndef daily_max(readings):\n    return max(readings)\n```" in md
    assert "> Every tide pool is a world in miniature." in md


def test_relative_links_are_made_absolute() -> None:
    _, ex = _article()
    md, _ = assemble(ex.blocks, "u")
    assert "[guide to rocky shores](https://fieldnotes.example/guides/rocky-shores)" in md


def test_block_types_and_heading_levels() -> None:
    _, ex = _article()
    types = [b.type for b in ex.blocks]
    for t in (BlockType.HEADING, BlockType.PARAGRAPH, BlockType.LIST, BlockType.TABLE):
        assert t in types
    assert BlockType.CODE in types
    assert BlockType.QUOTE in types
    assert [b.level for b in ex.blocks if b.type is BlockType.HEADING] == [1, 2, 2]


def test_provenance_spans_and_xpaths() -> None:
    root, ex = _article()
    md, blocks = assemble(ex.blocks, "https://fieldnotes.example/x")
    tree = root.getroottree()
    for block in blocks:
        p = block.provenance
        assert md[p.char_start : p.char_end] == block.text
        assert p.source == "https://fieldnotes.example/x"
        assert p.dom_path is not None
        assert tree.xpath(p.dom_path), f"XPath {p.dom_path} does not resolve"
    h1 = tree.xpath(blocks[0].provenance.dom_path)[0]
    assert h1.tag == "h1"


def test_metadata() -> None:
    root = parse_html(fixture_text("article.html"))
    meta = extract_metadata(
        root, url="https://fieldnotes.example/guides/tide-pools", json_ld=iter_json_ld(root)
    )
    assert meta.title == "Understanding Tide Pools"
    assert meta.description == "A field guide to the ecology of rocky intertidal zones."
    assert meta.language == "en"
    assert meta.canonical_url == "https://fieldnotes.example/guides/tide-pools"
    assert meta.author == "Field Notes Staff"
    assert meta.published_at == "2025-03-14T09:00:00Z"
    assert meta.site_name == "Field Notes"
    assert meta.structured_data[0]["@type"] == "Article"


def test_metadata_falls_back_to_json_ld() -> None:
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "Article", "headline": "From LD", "author": [{"name": "A"}, {"name": "B"}],'
        ' "datePublished": "2024-01-02"}</script></head><body></body></html>'
    )
    root = parse_html(html)
    meta = extract_metadata(root, url=None, json_ld=iter_json_ld(root))
    assert meta.title == "From LD"
    assert meta.author == "A, B"
    assert meta.published_at == "2024-01-02"


def test_parse_html_tolerates_junk() -> None:
    for text in ("", "   ", '<?xml version="1.0"?><html><body><p>x</p></body></html>'):
        root = parse_html(text)
        assert root.tag == "html"


def test_invalid_json_ld_is_ignored() -> None:
    root = parse_html('<script type="application/ld+json">{not json</script>')
    assert iter_json_ld(root) == []


# ---------------------------------------------------------------- benchmark-driven rules

_PROSE = (
    "Researchers measured the tide every hour for a full year, and the data shows a clear "
    "seasonal pattern that matches the predictions of the original model."
)


def _md(html: str) -> str:
    root = parse_html(html)
    md, _ = assemble(extract_html(root, "https://x.example/a").blocks, "u")
    return md


def test_split_article_sections_are_merged() -> None:
    sections = "".join(
        f'<div class="ad"><p>Advertisement {i}</p></div>'
        f'<section><div class="story-body"><p>Part {i}. {_PROSE}</p>'
        f"<p>More {i}. {_PROSE}</p></div></section>"
        for i in range(4)
    )
    md = _md(f"<html><body><article>{sections}</article><aside>Popular</aside></body></html>")
    for i in range(4):
        assert f"Part {i}." in md
    assert "Advertisement" not in md
    assert "Popular" not in md


def test_wrapper_class_words_do_not_drop_the_article() -> None:
    body = "".join(f"<p>{_PROSE} ({i})</p>" for i in range(6))
    html = (
        '<html><body><div class="l-sidebar-fixed l-article-body-segment has-share">'
        f"{body}</div></body></html>"
    )
    assert "(5)" in _md(html)


def test_whole_page_form_is_kept_but_search_form_dropped() -> None:
    body = "".join(f"<p>{_PROSE} ({i})</p>" for i in range(6))
    html = (
        '<html><body><form id="aspnetForm"><form class="search"><input name="q">'
        f"<p>Search the site</p></form><div>{body}</div></form></body></html>"
    )
    md = _md(html)
    assert "(5)" in md
    assert "Search the site" not in md


def test_captions_bylines_and_link_strips_are_dropped() -> None:
    body = "".join(f"<p>{_PROSE} ({i})</p>" for i in range(5))
    related = "".join(f'<li><a href="/s{i}">Related story number {i}</a></li>' for i in range(6))
    html = (
        "<html><body><article>"
        '<div class="byline">By Jane Reporter</div>'
        '<figure><img src="a.jpg" alt=""><figcaption>A tide pool at dawn.</figcaption></figure>'
        f'{body}<ul class="list">{related}</ul>'
        "</article></body></html>"
    )
    md = _md(html)
    assert "(4)" in md
    for junk in ("Jane Reporter", "tide pool at dawn", "Related story"):
        assert junk not in md


def test_div_paragraphs_count_for_container_choice() -> None:
    paras = "".join(f'<div class="zn-body__paragraph">{_PROSE} ({i})</div>' for i in range(6))
    html = (
        '<html><body><div class="nav"><a href="/">Home</a></div>'
        f'<div class="l-container">{paras}</div></body></html>'
    )
    md = _md(html)
    assert "(0)" in md
    assert "(5)" in md
    assert "Home" not in md
