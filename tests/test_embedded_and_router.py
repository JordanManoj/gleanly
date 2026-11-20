from __future__ import annotations

from gleanly.clean import extract_html, parse_html
from gleanly.fetch import router
from gleanly.fetch.embedded import extract_embedded

from .conftest import fixture_text


def test_next_data_is_used_for_spa() -> None:
    root = parse_html(fixture_text("spa_next.html"))
    visible = extract_html(root, None, method="http")
    assert visible.word_count == 0
    assert router.looks_js_rendered(root, visible)

    embedded = extract_embedded(root, "https://garden.example/posts/composting")
    assert embedded is not None
    assert embedded.method == "embedded"
    assert embedded.blocks[0].text.startswith("Composting turns kitchen scraps")
    assert len(embedded.blocks) == 2  # two paragraphs
    assert embedded.blocks[0].dom_path == "/html/body/script $.props.pageProps.post.body"
    assert router.better(embedded, visible)


def test_json_ld_article_body_with_graph() -> None:
    root = parse_html(fixture_text("jsonld_article.html"))
    embedded = extract_embedded(root, None)
    assert embedded is not None
    assert embedded.blocks[0].text == "# Le pain au levain"
    assert embedded.blocks[1].text.startswith("Le levain est un mélange")
    assert embedded.blocks[1].dom_path is not None
    assert embedded.blocks[1].dom_path.endswith("$[1].articleBody")


def test_html_inside_json_is_converted() -> None:
    body = "<p>" + " ".join(["word"] * 50) + ".</p><h2>Part two</h2><p>More text here.</p>"
    html = (
        '<html><body><div id="app"></div><script type="application/ld+json">'
        '{"@type": "BlogPosting", "articleBody": ' + _json_str(body) + "}</script></body></html>"
    )
    embedded = extract_embedded(parse_html(html), None)
    assert embedded is not None
    assert "## Part two" in [b.text for b in embedded.blocks]


def _json_str(s: str) -> str:
    import json

    return json.dumps(s)


def test_no_embedded_data() -> None:
    root = parse_html("<html><body><p>Short page.</p></body></html>")
    assert extract_embedded(root, None) is None


def test_server_rendered_article_is_not_js_suspect() -> None:
    root = parse_html(fixture_text("article.html"))
    ex = extract_html(root, None, method="http")
    assert not router.is_poor(ex)
    assert not router.looks_js_rendered(root, ex)
    assert not router.better(None, ex)
