# Changelog

All notable changes to gleanly are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) as described in [docs/versioning.md](docs/versioning.md).

## [Unreleased]

### Fixed

- Low OCR confidence now caps the trust score (at most 2 x confidence - 0.8 below 0.8): a
  Malayalam newspaper photo read without a Malayalam model scored 0.82, now 0.29. The
  warning names an unsupported script as a possible cause.

### Changed

- `gleanly[ocr]` now installs glyphly 0.1, gleanly's own OCR engine: OCR works with
  `pip install` alone, no Tesseract. Tesseract stays available (`ocr_engine="tesseract"`).

### Added

- `python -m gleanly`: runs the CLI even when pip's Scripts folder is not on PATH
  (common on Windows, where `gleanly` is then "not recognized").
- Shop pages: product facts from schema.org JSON-LD (`Product`, `ProductGroup` with
  variants, `Offer`, `AggregateOffer`) as a table under the title (name, brand, price,
  availability, colour, sizes, SKU/MPN/GTIN, rating) and as `Document.metadata.product`.
  The shop's own description is added when the chosen text lacks it.
- `bench/shop.py`: checks that product facts are found on real shop pages (saved locally,
  never committed).
- OCR engine choice: `ocr_engine="auto" | "glyphly" | "tesseract"` and `--ocr-engine`.
  `auto` uses glyphly (no Tesseract needed) when it is installed, else Tesseract; images,
  scanned PDF pages and the PDF text-layer check all work with either engine.

### Changed

- Any language: words are counted by characters in scripts without spaces (Chinese,
  Japanese; Thai, Lao, Khmer and Burmese at about four characters per word), the extraction
  cross-check compares those scripts character by character, Indic vowel signs stay part of
  their word, and sentence ends include the Devanagari danda, Arabic, Armenian, Ethiopic,
  Burmese and Khmer stops and full-width CJK stops (Thai and Lao need none). Real Wikipedia
  articles: a Chinese page that came back as CSS with 11 "words" is now extracted cleanly;
  extraction confidence Japanese 0.07 -> 0.93, Hindi 0.19 -> 0.90, Thai 0.48 -> 0.84;
  English benchmark unchanged (0.900 -> 0.901).

### Fixed

- The block classifier took the text of `<style>` and `<script>` nested inside inline
  elements (Wikipedia reference lists), so CSS could appear in the Markdown.

### Changed (continued)

- Repeated paragraphs and lists (same text, case and spacing ignored) are kept once.
- Text from framework data (`__NEXT_DATA__` and similar) is kept only if the page also
  shows it, unless the page is rendered by JavaScript; when the visible page gives at
  least as much text, it is preferred over framework data. Text declared as the article
  (JSON-LD `articleBody`) is still trusted.
- The trust score can no longer contradict its warnings: with extraction confidence
  below 0.7 it is at most confidence + 0.3, and "check the result" warnings lower it.

## [0.1.0a2] - 2026-11-22

### Fixed

- `pip install --pre gleanly` installed unfinished dependency releases (httpx 1.0.dev,
  lxml 7 beta) and `load()` failed with `httpx has no attribute AsyncClient`. Dependencies
  now have upper bounds on their major versions, the README uses a plain
  `pip install gleanly`, and CI installs the built wheel (also with pre-releases allowed)
  and converts a page before anything is published.
- License detection matched a license address anywhere inside a link, so
  `https://other.example/?x=creativecommons.org/licenses/by/4.0` counted as CC-BY. It
  now requires the link's real host and path (found by CodeQL).

## [0.1.0a1] - 2026-11-22

First public alpha.

### Added

- `load()` / `aload()` / `Client`: URLs and local files to clean Markdown with metadata,
  a trust score (`QualityReport`), AI-use compliance evidence (`ComplianceInfo`) and
  block-level provenance.
- Ethical fetch ladder: plain HTTP with an honest User-Agent, embedded data (JSON-LD,
  `__NEXT_DATA__`), optional Playwright rendering (`[browser]`); robots.txt, Crawl-delay and
  per-host rate limits.
- Main-content extraction with an independent cross-check: `extraction_confidence`,
  `extraction_support`, `extraction_coverage`, per-block `support`; optional reader
  comments (`include_comments`).
- Compliance evidence: robots.txt and AI-crawler opt-outs, TDMRep, ai.txt, `noai`,
  license detection, PII flags; verdict `ai_use` with `conditions` and a disclaimer.
- PDFs (`[pdf]`): headings, lists, de-hyphenation, running headers removed, page and
  bounding-box provenance; text layer checked against OCR.
- OCR (`[ocr]` + Tesseract): images, image URLs and scanned PDF pages, with background
  flattening and text-size normalisation; `ocr_confidence` in the trust score.
- `search()` / `asearch()`: Wikipedia, Brave and SearXNG backends (official APIs only),
  reciprocal rank fusion, every result fetched and scored.
- Search agreement (experimental): `SearchResponse.agreement` with corroborated and
  conflicting numeric/date facts, each source quoted with its location.
- CLI: `gleanly load` and `gleanly search`.
- Benchmarks (`bench/`): web extraction on 8 datasets, OCR standard and hard suites,
  confidence calibration.
