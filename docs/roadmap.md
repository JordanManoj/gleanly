# gleanly: goals, principles and roadmap

> Package name: `gleanly` (PyPI name, import name and CLI command; confirmed free on PyPI on 2026-11-19).

## What we are building

A free, open-source Python library (`pip install gleanly`) that combines in ONE package:

- **Scraping** like Firecrawl: URL → clean Markdown + metadata, crawling.
- **OCR** like Tesseract (uses Tesseract as a dependency): images, scans, PDFs → text.
- **Search** like Tavily: multi-backend web search (SearXNG, Brave, etc.) + local reranking.

Single entry points: `load(source)` for any URL/file, `search(query)` for the web.

### Novelty — what makes it different (these are first-class features, not add-ons)

1. **Cross-source trust score** — every document (web, PDF, OCR) gets a comparable `quality` report and score. Later phases calibrate it against downstream RAG accuracy.
2. **Compliance metadata** — per document: robots.txt status, text-and-data-mining opt-out (TDMRep: `tdm-reservation` header / `/.well-known/tdmrep.json`, ai.txt), detected content license, PII flags. Answer: "usable for AI training? yes / no / unclear".
3. **Provenance** — every output block (later: sentence) maps back to its source location (URL + DOM path, PDF page + bbox, image region).
4. **Cross-source agreement** (search phase) — flag when sources contradict each other.
5. **Fetch ladder** — try legitimate routes cheapest-first, learn the best route per domain, explain failures clearly.
6. **One process, no Docker required.**

## Hard rules

- **Write all code from scratch.** Do NOT copy or translate code from Firecrawl (AGPL-3.0). Studying its API/output format for compatibility is fine.
- **License: Apache-2.0.** Only use dependencies with permissive licenses (MIT, BSD, Apache-2.0, etc.). Check each new dependency's license before adding it and list it in `docs/dependencies.md`. No GPL/AGPL dependencies in the core.
- **Ethical fetching only.** No anti-bot evasion: no fingerprint spoofing, no CAPTCHA solving, no proxy rotation to dodge blocks, no fake browser user agents. Use an honest User-Agent that identifies the library with a contact URL. Respect robots.txt by default. Rate-limit per domain. When blocked, report it and use fallbacks (archives, RSS, sitemaps, official APIs).
- **Heavy dependencies are optional extras**: `gleanly[browser]` (Playwright), `gleanly[ocr]` (Tesseract bindings), `gleanly[search]`, `gleanly[llm]`. Core install must stay light.
- Typed public API (Pydantic v2 models for outputs). Sync AND async versions (`load` / `aload`).
- Every feature ships with tests. No real network calls in unit tests — mock HTTP (e.g. respx) and use saved HTML fixtures.

## Tooling

- Python 3.10+, `uv` for env/deps, `hatchling` build backend, `pyproject.toml`.
- `ruff` (lint + format), `pyright` or `mypy` (types), `pytest` (+ `pytest-asyncio`).
- GitHub Actions CI: lint, type-check, tests on 3.10–3.13. Release workflow publishing to PyPI on version tags (trusted publishing).
- `src/` layout.

## Target package structure

```
src/gleanly/
  __init__.py          # load, aload, search, asearch
  models.py            # Document, Block, QualityReport, ComplianceInfo, Provenance, FetchTrace
  fetch/               # fetch ladder: http.py, embedded.py, browser.py, archive.py, robots.py, ratelimit.py, router.py
  clean/               # main-content extraction, HTML → Markdown (tables/code preserved)
  ocr/                 # Tesseract wrapper, preprocessing, confidence
  quality/             # quality signals + trust score
  compliance/          # robots, TDMRep, ai.txt, license detection, PII flags
  search/              # backends + reranking (later phase)
  cli.py               # `gleanly load URL -o out.md`
tests/
bench/                 # extraction-quality benchmark (later)
docs/
```

## Core data model (starting point — refine as needed)

- `Document`: `source`, `markdown`, `blocks: list[Block]`, `metadata`, `quality: QualityReport`, `compliance: ComplianceInfo`, `fetch_trace: FetchTrace`.
- `Block`: `text`, `type` (heading/paragraph/table/code/list), `provenance: Provenance`.
- `QualityReport`: individual signals (e.g. text density, boilerplate ratio, extraction method, language, OCR confidence when relevant) + `score` in [0, 1] + human-readable `warnings`.
- `ComplianceInfo`: `robots_allowed`, `tdm_reserved`, `license`, `pii_detected`, `ai_use` ∈ {"allowed", "disallowed", "unclear"} + `evidence` list.
- `FetchTrace`: each ladder step tried, result, timing, final reason on failure.

## Methodology (decided 2026-11-19)

We build on established methods (Readability-style extraction, Tesseract, rank fusion, cross-encoders) and add a layer they lack. Core principle: **every method reports its confidence and evidence, and independent methods cross-check each other**; agreement/disagreement becomes a trust signal.

- **Extraction:** cross-page template learning (boilerplate = what repeats across sibling pages of a site), extractor ensemble (ours + embedded data + an established extractor) with per-block confidence and per-block boilerplate probability, embedded-vs-visible text cross-check.
- **Fetching:** learned per-domain routing, conditional requests (ETag/Last-Modified), legitimate fallbacks.
- **OCR/PDF:** confidence-guided re-OCR of uncertain regions; PDF text layer vs OCR cross-check per page.
- **Search:** trust- and compliance-aware ranking; claim-level agreement with provenance.
- **Trust score:** one score across source types, calibrated against downstream RAG accuracy.

**Benchmark first:** every improvement is added on its own and kept only if it beats the baseline on `bench/`. Third-party benchmark pages are downloaded into `bench/data/` (git-ignored), never committed. Baselines (Trafilatura, readability-lxml) live in the `bench` dependency group only, never in the core.


## Roadmap

- **Phase 1 (current):** scaffold + `load()` for web pages — fetch ladder rungs 1–3 (plain HTTP → embedded data like JSON-LD/`__NEXT_DATA__` → optional Playwright), HTML → Markdown, metadata, QualityReport v0, ComplianceInfo v0 (robots + TDMRep), block-level provenance, CLI, tests, CI. **Done** except PyPI release setup (ai.txt and real-world regression pages added 2026-11-20).
- **Done (2026-11-19):** extraction benchmark + baselines (`bench/`), extractor tuned to F1 0.958; extraction confidence from an independent block classifier (`quality/crosscheck.py`: `QualityReport.extraction_confidence`, `Block.support`, also checks embedded text against visible text).
- **Done (2026-11-20):** 7 more benchmark datasets (WCEB, ~3,700 pages; `-d all`); form/byline fixes; block-classifier rescue (`clean/blocks.py`, `quality.extractor`). Held-out macro F1 0.902 (trafilatura 0.910, readability 0.900; tie without Dragnet, whose labels include comments).
- **Done (2026-11-20):** confidence v2: added coverage (missed prose), `confidence = support x sqrt(coverage)`, `QualityReport.extraction_support` / `extraction_coverage`; held-out AUROC 0.82 pooled over all 8 datasets (was 0.60).
- **Done (2026-11-20):** optional comments (`include_comments`, CLI `--comments`, `clean/comments.py`, `Block.role`): comment sections found by class/id, prose kept via the block classifier. Held-out: Dragnet 0.825 -> 0.901 (trafilatura 0.895), CETD 0.905 -> 0.934 (0.928). Off by default (hurts sets whose labels exclude comments).
- **Tried, not adopted (2026-11-20):** cross-page template learning; no headroom on CETD/CleanPortalEval (precision already ~1.0 there, errors are recall); see bench/README.md.
- **Phase 2 started (2026-11-20):** native PDFs via pypdfium2 (`gleanly[pdf]`, `src/gleanly/pdf/`): shared word->line->paragraph layout (also for OCR), headings by font size/bold, lists, de-hyphenation, running headers/footers learned across pages, page + bbox provenance, scanned pages reported. Tests use our own generated PDFs (`tests/pdfmaker.py`).
- **Done (2026-11-20):** OCR (`gleanly[ocr]` + Tesseract TSV, `src/gleanly/ocr/`) for images and scanned PDF pages; generated OCR benchmark (`bench/ocr.py`). Held-out CER 16.1% (plain Tesseract) -> 0.77% (background flattening + text-size normalisation). Layout self-check tried and dropped.
- **Done (2026-11-20):** PDF text layer vs OCR cross-check (`pdf/check.py`): implausible pages + a sample are OCR'd and compared; broken layers are replaced by OCR; agreement becomes the PDF's extraction_confidence (`pdf_check_pages`). Confidence-guided re-OCR tried and dropped (no gain).
- **Phase 2 done (2026-11-20):** status page, CLI `--no-ocr` / `--ocr-lang`.
- **Phase 3 started (2026-11-21):** `search()`/`asearch()`/`gleanly search` (`src/gleanly/search/`): backends Wikipedia (keyless), Brave (`BRAVE_API_KEY`), SearXNG (`SEARXNG_URL`), official APIs only; reciprocal rank fusion with URL normalisation; every hit fetched through `load()`; ranking v0 (relevance + fusion, x trust), `exclude_disallowed`. OCR open items: held-out hard-suite numbers, Courier enlargement cap, Tesseract+RapidOCR cross-check (runs need free memory).
- **Next up:** search benchmark (license-clean, offline-reproducible), then tuned ranking, then claim-level agreement. Later: docs/shop/non-English datasets.
- **Phase 2:** OCR for images/scanned PDFs via Tesseract, native PDFs; same Document model.
- **Phase 3:** `search()` — SearXNG + key-based backends, rank fusion, local cross-encoder reranking, agreement checking.
- **Phase 4:** archive fallbacks, per-domain learned routing, Web Bot Auth request signing, crawling, RAG chunking, Firecrawl/Tavily-compatible server mode, trust-score calibration, docs site.

## Working style

- **Honest review:** `docs/review.md` holds an unsugared scorecard (user / AI engineer / CEO) and every known weakness with the work that fixes it. Re-check and update it at every milestone; prefer work that makes gleanly usable by real people (availability, scale) over small benchmark gains.

- Plan before large changes; keep commits small with clear messages.
- Prefer well-maintained existing libraries over reinventing (with license check), but keep our own abstraction layer around them.
- Keep this file up to date when architecture decisions change.
