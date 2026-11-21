# Status

## Phase 1: web pages (done)

| Item | State | Notes |
| --- | --- | --- |
| Scaffold: `src/` layout, hatchling, uv, ruff, pyright, pytest | done | |
| `load` / `aload` / `Client` (shared robots cache + rate limits) | done | |
| Rung 1: plain HTTP, honest User-Agent, size cap, charset detection | done | |
| Rung 2: embedded data (JSON-LD `articleBody`, `__NEXT_DATA__`, JSON state) | done | Also applied to local HTML files |
| Rung 3: Playwright rendering (`[browser]` extra) | done | Only when the page looks JS-rendered and cheaper rungs failed |
| robots.txt (RFC 9309), Crawl-delay, per-host rate limiting | done | Unreachable/5xx robots.txt = disallow, 4xx = allow |
| HTML → Markdown: headings, lists, tables, code (with language), quotes, links | done | |
| Block-level provenance: XPath + char span (+ JSON path for embedded data) | done | |
| Metadata: title, description, language, canonical, author, dates, JSON-LD | done | |
| ComplianceInfo v0: robots, AI-crawler opt-outs, TDMRep, `ai.txt`, `noai`, license, PII | done | ai.txt: file-type rules match pages by content type; HTML "not found" pages ignored |
| QualityReport v0 + score | done | Heuristic, uncalibrated |
| Extraction benchmark (`bench/`): 8 datasets, dev/test split, baselines | done | Held-out macro F1 0.902 (trafilatura 0.910, readability 0.900) |
| Optional reader comments (`include_comments`, `--comments`, `Block.role`) | done | Held-out Dragnet 0.901 / CETD 0.934, both above trafilatura |
| Extraction confidence: independent cross-check, per-block `support` | done | v2 adds coverage (missed prose); held-out AUROC 0.82 over 8 datasets, no extra dependency |
| Real-world regression pages (news, docs, WordPress, shop) | done | Original content modelled on real layouts; golden Markdown files |
| CLI `gleanly load SOURCE -o out.md / out.json` | done | |
| Tests (no real network; respx + HTML fixtures) | done | |
| CI (lint, types, tests on 3.10–3.13, Linux/macOS/Windows) + release on tags | done | Tesseract installed on Linux so OCR tests run |

## Phase 2: PDFs and OCR (done)

| Item | State | Notes |
| --- | --- | --- |
| Native PDFs (`[pdf]` extra, pypdfium2) | done | Headings by size/bold, lists, de-hyphenation, page + bbox provenance, PDF metadata |
| Running headers/footers and page numbers learned across pages | done | |
| OCR (`[ocr]` extra + Tesseract): images, image URLs, scanned PDF pages | done | `ocr`, `ocr_lang`, `tesseract_cmd` options; `QualityReport.ocr_confidence` |
| OCR clean-up tuned on a generated benchmark (`bench/ocr.py`) | done | Held-out CER 16.1% (plain Tesseract) -> 0.77% |
| PDF text layer vs OCR cross-check | done | Broken layers replaced by OCR; agreement = PDF `extraction_confidence` |
| Tried and dropped | - | Layout self-check, confidence-guided re-OCR (no gain on the benchmark) |

Known limits: blurred scans are the largest OCR error (~4% CER); handwriting, tables in
scans and non-English OCR are not benchmarked yet; no public, license-clean corpus of
broken PDFs exists to benchmark the text-layer check.

### Open items before a first release (done by the maintainer)

- Make the GitHub repository public (the User-Agent contact URL points to it).
- Set up a PyPI trusted publisher and tag `v0.1.0a1` to register the `gleanly` name.

## Phase 3: search (in progress)

| Item | State | Notes |
| --- | --- | --- |
| `search` / `asearch` / `gleanly search`, `SearchResponse` model | done | Every result is a full `Document` |
| Backends: Wikipedia (keyless), Brave (`BRAVE_API_KEY`), SearXNG (`SEARXNG_URL`) | done | Official APIs only |
| Reciprocal rank fusion with URL normalisation | done | Pages several engines agree on rank higher |
| Ranking v0: relevance + fusion, weighted by trust; `exclude_disallowed` | done | Hand-set weights; benchmark next |
| Search benchmark, tuned ranking | next | |
| Claim-level agreement between sources | planned | |

## Later phases

See the roadmap in docs/roadmap.md: archives, crawling, learned routing, server mode and
trust-score calibration (4).
