"""Last steps on an HTML extraction, whichever rung produced it.

1. **Repeated blocks are kept once.** Responsive pages often ship the same paragraph two or
   three times (mobile and desktop layouts, a sticky copy of the price); framework data
   repeats text per country. A paragraph or list whose text (case and spacing ignored)
   already appeared is dropped. Headings, tables and code are left alone.
2. **Product facts.** When the page describes a product in schema.org JSON-LD, a small
   facts table (price, sizes, codes, ...) is placed right after the title, and the
   product is returned for ``Document.metadata.product``.
"""

from __future__ import annotations

from lxml.html import HtmlElement

from gleanly.clean.html import Extraction, RawBlock, markdown_to_plain
from gleanly.clean.product import find_product, product_blocks
from gleanly.models import BlockType, ProductInfo

_DEDUPE_TYPES = {BlockType.PARAGRAPH, BlockType.LIST}
MIN_DEDUPE_WORDS = 4  # short repeats ("Read more", "Share") are left to the extractor


def drop_repeats(blocks: list[RawBlock]) -> list[RawBlock]:
    seen: set[str] = set()
    out: list[RawBlock] = []
    for block in blocks:
        if block.type in _DEDUPE_TYPES and block.role == "main":
            key = " ".join(markdown_to_plain(block.text).split()).casefold()
            if len(key.split()) >= MIN_DEDUPE_WORDS:
                if key in seen:
                    continue
                seen.add(key)
        out.append(block)
    return out


def _contains(blocks: list[RawBlock], text: str) -> bool:
    """True if the start of ``text`` already appears in the blocks (case and spacing ignored)."""
    probe = " ".join(text.split()[:12]).casefold()
    plain = " ".join(" ".join(markdown_to_plain(b.text).split()) for b in blocks).casefold()
    return probe in plain


def finish_html(extraction: Extraction, root: HtmlElement) -> tuple[Extraction, ProductInfo | None]:
    blocks = drop_repeats(extraction.blocks)
    product = None
    found = find_product(root)
    if found is not None:
        product, script_path = found
        facts = product_blocks(product, script_path)
        if facts and product.description and not _contains(blocks, product.description):
            # The shop's own description, when the page text chosen lacks it (e.g. the
            # extractor kept the customer reviews instead).
            facts.append(
                RawBlock(
                    BlockType.PARAGRAPH,
                    product.description,
                    f"{script_path} (schema.org Product description)",
                    kind="embedded",
                )
            )
        if facts:
            at = 1 if blocks and blocks[0].type == BlockType.HEADING else 0
            if at == 0 and product.name:
                title = RawBlock(
                    BlockType.HEADING,
                    f"# {product.name}",
                    facts[0].dom_path,
                    1,
                    kind="embedded",
                )
                facts = [title, *facts]
            blocks = blocks[:at] + facts + blocks[at:]
    if len(blocks) != len(extraction.blocks) or found is not None:
        extraction.blocks = blocks
        extraction.refresh()
    return extraction, product


__all__ = ["drop_repeats", "finish_html"]
