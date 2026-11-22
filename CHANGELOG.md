# Changelog

All notable changes to gleanly are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) as described in [docs/versioning.md](docs/versioning.md).

## [Unreleased]

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
