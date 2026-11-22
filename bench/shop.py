"""Shop-page check: does gleanly return the facts a shopper or a price tracker needs?

uv run python -m bench.shop --fetch   # download the pages (robots.txt respected) once
uv run python -m bench.shop           # score the saved pages offline

Pages are saved to bench/data/shop/ (git-ignored, never committed). For each page the
expected facts (name, price, currency, a sentence of the description) are written down by
hand in SHOPS below, from the page as a visitor sees it. Reported per page:

- facts found in the Markdown (name, price, description sentence) and in
  ``metadata.product`` (name, price, currency);
- repeated text: share of paragraphs that are an exact repeat of an earlier one;
- word count, score and extraction confidence.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).parent / "data" / "shop"


@dataclass
class Shop:
    key: str
    url: str
    name: str  # words that must appear in the product name
    price: float
    currency: str
    sentence: str  # a few words from the product description


SHOPS = [
    Shop(
        "nike",
        "https://www.nike.com/de/t/air-jordan-4-retro-flight-club-schuh-herren-x4MSM19W/IM4002-100",
        "Air Jordan 4 Retro",
        146.99,
        "EUR",
        "Wer wie MJ fliegen wollte",
    ),
    Shop(
        "ikea",
        "https://www.ikea.com/de/de/p/billy-buecherregal-weiss-00263850/",
        "BILLY",
        49.99,
        "EUR",
        "Mit einem festen und 4 versetzbaren Böden",
    ),
]
# Tried on 2026-11-22 and left out: Bose, Decathlon and LEGO answer 403 to an honest
# client; Thomann's robots.txt disallows it; the Allbirds, Apple and Patagonia URLs served a
# collection page, a list of links and a maintenance page instead of a product.


def _money_in(text: str, price: float) -> bool:
    whole, cents = f"{price:.2f}".split(".")
    pattern = rf"{whole}[.,]{cents}" if cents != "00" else rf"{whole}(?:[.,]00)?"
    return re.search(rf"(?<![\d.,]){pattern}(?![\d])", text) is not None


def fetch() -> None:
    import httpx

    from gleanly import load
    from gleanly.config import LoadOptions
    from gleanly.errors import FetchError

    DATA.mkdir(parents=True, exist_ok=True)
    ua = LoadOptions().user_agent
    for shop in SHOPS:
        path = DATA / f"{shop.key}.html"
        if path.exists():
            continue
        try:
            load(shop.url)  # checks robots.txt and AI opt-outs the normal way
        except FetchError as exc:
            print(f"{shop.key}: not fetched: {exc}")
            continue
        r = httpx.get(shop.url, headers={"User-Agent": ua}, follow_redirects=True, timeout=30)
        path.write_bytes(r.content)
        print(f"{shop.key}: {r.status_code}, {len(r.content)} bytes")


def score() -> int:
    from gleanly import load

    rows = []
    for shop in SHOPS:
        path = DATA / f"{shop.key}.html"
        if not path.exists():
            print(f"{shop.key}: missing, run with --fetch")
            continue
        doc = load(str(path))
        md = doc.markdown
        flat = " ".join(md.split())
        paras = [p.strip() for p in md.split("\n\n") if len(p.split()) >= 4]
        repeats = len(paras) - len({" ".join(p.split()).casefold() for p in paras})
        p = getattr(doc.metadata, "product", None)  # absent before 0.1.0a3
        checks = {
            "name": shop.name.casefold() in flat.casefold(),
            "price": _money_in(flat, shop.price),
            "desc": shop.sentence.casefold() in flat.casefold(),
            "meta": bool(
                p
                and p.name
                and shop.name.casefold() in p.name.casefold()
                and p.price == shop.price
                and p.currency == shop.currency
            ),
        }
        rows.append((shop.key, checks, repeats / max(len(paras), 1), doc))
    print(f"{'page':10} name price desc meta  repeats  words  score  confidence")
    for key, checks, rep, doc in rows:
        marks = "  ".join("yes " if v else "NO  " for v in checks.values())
        conf = doc.quality.extraction_confidence
        print(
            f"{key:10} {marks} {rep:6.0%} {doc.quality.word_count:6d}  {doc.quality.score:.2f}"
            f"   {conf if conf is not None else '-'}"
        )
    if rows:
        found = sum(sum(c.values()) for _, c, _, _ in rows)
        print(f"\nfacts found: {found}/{4 * len(rows)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench.shop")
    parser.add_argument("--fetch", action="store_true", help="download missing pages first")
    args = parser.parse_args(argv)
    if args.fetch:
        fetch()
    return score()


if __name__ == "__main__":
    sys.exit(main())
