"""Product facts from schema.org data (JSON-LD ``Product``, ``ProductGroup``, ``Offer``).

Shop pages often bury the facts people want (price, sizes, colour, product codes) in
scripts, while the visible text is mostly delivery and returns boilerplate. Most shops
also publish those facts as schema.org JSON-LD for search engines; this module reads them
into a :class:`~gleanly.models.ProductInfo` and a small Markdown table placed at the top
of the document, with provenance pointing at the JSON-LD script.
"""

from __future__ import annotations

from typing import Any

from lxml.html import HtmlElement

from gleanly.clean.html import RawBlock
from gleanly.clean.metadata import iter_json_ld, json_ld_objects
from gleanly.models import BlockType, ProductInfo

_PRODUCT_TYPES = {"product", "productgroup", "productmodel", "individualproduct", "vehicle"}


def _types(obj: dict[str, Any]) -> set[str]:
    t = obj.get("@type")
    values = t if isinstance(t, list) else [t]
    return {v.rsplit("/", 1)[-1].lower() for v in values if isinstance(v, str)}


def _text(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value")
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, (str, int, float))), None)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if isinstance(value, str):
        value = " ".join(value.replace("\xa0", " ").split())
        return value or None
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(" ", "")
        if "," in s and "." not in s:
            s = s.replace(",", ".")  # 146,99
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return None
    return None


def _offers(obj: dict[str, Any]) -> list[dict[str, Any]]:
    raw = obj.get("offers")
    items = raw if isinstance(raw, list) else [raw]
    out: list[dict[str, Any]] = []
    for o in items:
        if not isinstance(o, dict):
            continue
        out.append(o)
        nested = o.get("offers")  # AggregateOffer with a list of offers
        if isinstance(nested, list):
            out += [n for n in nested if isinstance(n, dict)]
    return out


def _availability(value: Any) -> str | None:
    s = _text(value)
    return s.rsplit("/", 1)[-1] if s else None  # https://schema.org/InStock -> InStock


def _collect(products: list[dict[str, Any]]) -> ProductInfo:
    main = products[0]
    variants = [v for v in main.get("hasVariant") or [] if isinstance(v, dict)]
    everything = [main, *variants]

    def first(key: str) -> str | None:
        for p in everything:
            if (v := _text(p.get(key))) is not None:
                return v
        return None

    prices: list[float] = []
    currency = availability = None
    available_sizes: list[str] = []
    sizes: list[str] = []
    for p in everything:
        size = _text(p.get("size"))
        if size and size not in sizes:
            sizes.append(size)
        for o in _offers(p):
            for key in ("price", "lowPrice", "highPrice"):
                if (n := _number(o.get(key))) is not None and n > 0:
                    prices.append(n)
            currency = currency or _text(o.get("priceCurrency"))
            avail = _availability(o.get("availability"))
            availability = availability or avail
            if size and avail and avail.lower() in ("instock", "limitedavailability"):
                available_sizes.append(size)

    rating = review_count = None
    agg = main.get("aggregateRating")
    if isinstance(agg, dict):
        rating = _number(agg.get("ratingValue"))
        review_count = _number(agg.get("reviewCount") or agg.get("ratingCount"))

    name = _text(main.get("name"))
    if name is None and variants:
        name = _text(variants[0].get("name"))
    return ProductInfo(
        name=name,
        brand=first("brand"),
        price=min(prices) if prices else None,
        price_max=max(prices) if prices and max(prices) != min(prices) else None,
        currency=currency,
        availability=availability,
        color=first("color"),
        sizes=sizes,
        available_sizes=available_sizes,
        sku=first("sku"),
        mpn=first("mpn"),
        gtin=first("gtin")
        or first("gtin13")
        or first("gtin12")
        or first("gtin14")
        or first("gtin8"),
        rating=rating,
        review_count=int(review_count) if review_count is not None else None,
        description=_text(main.get("description")) or first("description"),
    )


def find_product(root: HtmlElement) -> tuple[ProductInfo, str] | None:
    """The page's main product from JSON-LD, with the script's XPath; None if absent."""
    for script_path, data in iter_json_ld(root):
        objs = [o for o in json_ld_objects(data) if _types(o) & _PRODUCT_TYPES]
        if not objs:
            continue
        # Prefer a ProductGroup (it lists the variants), then the first product.
        objs.sort(key=lambda o: "productgroup" not in _types(o))
        info = _collect(objs)
        if info.name:
            return info, script_path
    return None


def _money(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") if value != int(value) else f"{value:.0f}"


def facts_table(info: ProductInfo) -> str:
    rows: list[tuple[str, str]] = []
    if info.brand:
        rows.append(("Brand", info.brand))
    if info.price is not None:
        price = _money(info.price)
        if info.price_max is not None:
            price += f" to {_money(info.price_max)}"
        rows.append(("Price", f"{price} {info.currency or ''}".strip()))
    if info.availability:
        rows.append(("Availability", info.availability))
    if info.color:
        rows.append(("Colour", info.color))
    if info.sizes:
        rows.append(("Sizes", ", ".join(info.sizes)))
        if info.available_sizes and len(info.available_sizes) < len(info.sizes):
            rows.append(("In stock", ", ".join(info.available_sizes)))
    for label, value in (("SKU", info.sku), ("MPN", info.mpn), ("GTIN", info.gtin)):
        if value:
            rows.append((label, value))
    if info.rating is not None:
        rating = _money(info.rating)
        if info.review_count:
            rating += f" ({info.review_count} reviews)"
        rows.append(("Rating", rating))
    if not rows:
        return ""
    cell = lambda s: s.replace("|", "\\|")  # noqa: E731
    lines = ["| Product | " + cell(info.name or "") + " |", "| --- | --- |"]
    lines += [f"| {k} | {cell(v)} |" for k, v in rows]
    return "\n".join(lines)


def product_blocks(info: ProductInfo, script_path: str) -> list[RawBlock]:
    table = facts_table(info)
    if not table:
        return []
    return [
        RawBlock(BlockType.TABLE, table, f"{script_path} (schema.org Product)", kind="embedded")
    ]


__all__ = ["facts_table", "find_product", "product_blocks"]
