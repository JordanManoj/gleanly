# Status

## Phase 1: web pages (in progress)

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
| Extraction benchmark (`bench/`) with dev/test split + baselines | done | F1 0.958 on 181 pages |
| Optional reader comments (`include_comments`, `--comments`, `Block.role`) | done | Held-out Dragnet 0.901 / CETD 0.934, both above trafilatura |
| Extraction confidence: independent cross-check, per-block `support` | done | v2 adds coverage (missed prose); held-out AUROC 0.82 over 8 datasets, no extra dependency |
| CLI `gleanly load URL -o out.md / out.json` | done | |
| Tests (no real network; respx + HTML fixtures) | done | |
| CI (lint, types, tests on 3.10–3.13) + release on tags | done | Needs the GitHub repo + PyPI trusted publisher |

### Open items before a first release

- Register the `gleanly` name on PyPI (first release) and create the GitHub repository.
- Set the real project URL in `config.PROJECT_URL` (it goes into the User-Agent).
- A small real-world HTML fixture set for regression tests of the extractor.

## Later phases

See the roadmap in docs/roadmap.md: PDFs/OCR (2), `search()` (3), archives, crawling,
learned routing, server mode and benchmark (4).
