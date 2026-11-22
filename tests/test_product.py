"""Shop pages: product facts, repeated text, framework data that the page does not show."""

from __future__ import annotations

import json
from pathlib import Path

from gleanly import load
from gleanly.clean import parse_html
from gleanly.clean.finish import drop_repeats
from gleanly.clean.html import RawBlock
from gleanly.clean.product import facts_table, find_product
from gleanly.fetch.embedded import extract_embedded
from gleanly.models import BlockType, ProductInfo

DESCRIPTION = (
    "A light trail shoe with a grippy outsole, a breathable upper and a cushioned midsole "
    "that stays comfortable on long days in the hills and on wet forest paths."
)


def _ld(obj: object) -> str:
    return f'<script type="application/ld+json">{json.dumps(obj)}</script>'


GROUP = {
    "@context": "https://schema.org",
    "@type": "ProductGroup",
    "name": "Ridge Runner 2",
    "brand": {"@type": "Brand", "name": "Northpine"},
    "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.6", "reviewCount": 212},
    "hasVariant": [
        {
            "@type": "Product",
            "name": "Ridge Runner 2 - Size 42",
            "size": "42",
            "color": "Moss/Black",
            "mpn": "RR2-042",
            "gtin13": "4006381333931",
            "description": DESCRIPTION,
            "offers": {
                "@type": "Offer",
                "price": "129.95",
                "priceCurrency": "EUR",
                "availability": "https://schema.org/InStock",
            },
        },
        {
            "@type": "Product",
            "size": "43",
            "offers": {
                "@type": "Offer",
                "price": 139.95,
                "priceCurrency": "EUR",
                "availability": "https://schema.org/OutOfStock",
            },
        },
    ],
}


def test_product_group_with_variants() -> None:
    root = parse_html(f"<html><head>{_ld(GROUP)}</head><body></body></html>")
    found = find_product(root)
    assert found is not None
    info, path = found
    assert path.endswith("script")
    assert info.name == "Ridge Runner 2"
    assert info.brand == "Northpine"
    assert (info.price, info.price_max, info.currency) == (129.95, 139.95, "EUR")
    assert info.sizes == ["42", "43"]
    assert info.available_sizes == ["42"]
    assert info.color == "Moss/Black"
    assert (info.mpn, info.gtin) == ("RR2-042", "4006381333931")
    assert (info.rating, info.review_count) == (4.6, 212)
    assert info.description == DESCRIPTION
    table = facts_table(info)
    assert "| Price | 129.95 to 139.95 EUR |" in table
    assert "| In stock | 42 |" in table
    assert "| Rating | 4.6 (212 reviews) |" in table


def test_graph_product_with_aggregate_offer_and_escaping() -> None:
    data = {
        "@graph": [
            {"@type": "WebPage", "name": "Shop"},
            {
                "@type": ["Product"],
                "name": "Mug | Large",
                "sku": "MUG-L",
                "offers": {
                    "@type": "AggregateOffer",
                    "lowPrice": "9,50",
                    "highPrice": "12",
                    "priceCurrency": "GBP",
                },
            },
        ]
    }
    info, _ = find_product(parse_html(f"<html><head>{_ld(data)}</head></html>")) or (None, "")
    assert info is not None
    assert (info.price, info.price_max, info.currency, info.sku) == (9.5, 12.0, "GBP", "MUG-L")
    assert "| Product | Mug \\| Large |" in facts_table(info)


def test_no_product_on_an_article() -> None:
    article = {"@type": "NewsArticle", "headline": "Tide report", "articleBody": "x " * 50}
    assert find_product(parse_html(f"<html><head>{_ld(article)}</head></html>")) is None
    assert facts_table(ProductInfo()) == ""


def test_repeated_paragraphs_are_kept_once() -> None:
    para = "Free delivery on orders over fifty euros."
    blocks = [
        RawBlock(BlockType.HEADING, "# Price", None, 1),
        RawBlock(BlockType.PARAGRAPH, para, "/a"),
        RawBlock(BlockType.PARAGRAPH, "Free  DELIVERY on orders over fifty euros.", "/b"),
        RawBlock(BlockType.PARAGRAPH, "Share", "/c"),
        RawBlock(BlockType.PARAGRAPH, "Share", "/d"),  # too short to judge: kept
        RawBlock(BlockType.HEADING, "# Price", None, 1),  # headings are left alone
    ]
    kept = drop_repeats(blocks)
    assert [b.dom_path for b in kept] == [None, "/a", "/c", "/d", None]


def _state_page(visible_words: int) -> str:
    """A Next.js-style page whose data holds delivery terms for several countries."""
    shown = "Delivery costs 5 EUR on orders under 99 EUR and returns are free for sixty days."
    hidden = "Delivery costs 4.50 GBP on orders under 99 GBP and returns are free for sixty days."
    filler = " ".join(["Walk"] + ["further"] * visible_words)
    state = {
        "props": {
            "story": DESCRIPTION + " " + DESCRIPTION,
            "de": shown + " " + "More text about delivery and returns in Germany. " * 4,
            "fr": shown + " " + "More text about delivery and returns in Germany. " * 4,
            "gb": hidden + " " + "More text about delivery and returns in Britain. " * 4,
        }
    }
    body = (
        f"<p>{DESCRIPTION} {DESCRIPTION}</p>"
        f"<p>{shown} {'More text about delivery and returns in Germany. ' * 4}</p>"
        f"<p>{filler}.</p>"
    )
    return (
        "<html><body><div id='__next'>"
        f"{body if visible_words else ''}</div>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(state)}</script>'
        "</body></html>"
    )


def test_state_text_must_be_visible_when_the_page_shows_text() -> None:
    ex = extract_embedded(parse_html(_state_page(200)), None)
    assert ex is not None
    assert ex.extractor == "state"
    text = " ".join(b.text for b in ex.blocks)
    assert "GBP" not in text  # in the data, not on the page
    assert text.count("Delivery costs 5 EUR") == 1  # stored per country, kept once


def test_state_text_is_kept_on_a_javascript_only_page() -> None:
    ex = extract_embedded(parse_html(_state_page(0)), None)
    assert ex is not None
    text = " ".join(b.text for b in ex.blocks)
    assert "GBP" in text  # nothing visible to check against: keep the prose
    assert text.count("Delivery costs 5 EUR") == 1


def test_product_page_end_to_end(tmp_path: Path) -> None:
    page = (
        f"<html><head><title>Ridge Runner 2</title>{_ld(GROUP)}</head><body>"
        "<h1>Ridge Runner 2</h1><p>129,95 EUR</p>"
        f"<p>{DESCRIPTION}</p><p>{DESCRIPTION}</p>"
        "<footer><a href='/a'>Help</a> <a href='/b'>Stores</a></footer></body></html>"
    )
    path = tmp_path / "shoe.html"
    path.write_text(page, encoding="utf-8")
    doc = load(str(path))
    assert doc.metadata.product is not None
    assert doc.metadata.product.price == 129.95
    md = doc.markdown
    assert md.startswith("# Ridge Runner 2\n\n| Product | Ridge Runner 2 |")
    assert md.count(DESCRIPTION) == 1
    table = next(b for b in doc.blocks if b.type == BlockType.TABLE)
    assert "schema.org Product" in (table.provenance.dom_path or "")


def test_score_cannot_contradict_low_confidence() -> None:
    from gleanly.clean.html import Extraction
    from gleanly.quality import compute_quality

    blocks = [RawBlock(BlockType.PARAGRAPH, DESCRIPTION, f"/p{i}") for i in range(8)]
    ex = Extraction(blocks, "http", page_chars=2000)
    sure = compute_quality(ex, raw_size=5000, extraction_confidence=0.95)
    unsure = compute_quality(ex, raw_size=5000, extraction_confidence=0.18)
    assert sure.score > 0.8
    assert unsure.score <= 0.18 + 0.3
    assert any("Low extraction confidence" in w for w in unsure.warnings)
