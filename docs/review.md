# Honest review and work to be done

A standing, unsugared review of gleanly from three viewpoints: a user with large workloads,
an experienced AI engineer, and the CEO of a company deciding whether to adopt it.
**Re-check this file at every milestone** (and at least every few working sessions): update
the scores, tick what is done, add new weaknesses as they are found. The goal is momentum:
real users, a product a customer could buy into, and a portfolio project that holds up to
an expert's scrutiny.

## Scorecard

| Date | User (large work) | AI engineer (technology) | CEO (adopt today) | Overall |
| --- | --- | --- | --- | --- |
| 2026-11-22 | 25 | 55-60 | 30 | ~40 |

## Weaknesses and the work that fixes them

Status: `todo` / `doing` / `done`. Each item says how we will know it is fixed.

### Availability and trust in the project

| # | Weakness | Work | Done when | Status |
| --- | --- | --- | --- | --- |
| A1 | Nobody can install it: private repo, not on PyPI, version 0.1.0.dev0 | Public repo + PyPI trusted publishing + `v0.1.0a1` (maintainer does the account steps) | `pip install gleanly` works for a stranger | todo |
| A2 | No users, no feedback | Alpha announcement, issue templates, a short "try it" guide; ask 5-10 people to try it | 5+ outside users or issues | todo |
| A3 | No promise the API stays stable | Versioning policy (SemVer, deprecation warnings), CHANGELOG | CHANGELOG and policy in the repo | todo |
| A4 | One maintainer (bus factor 1) | CONTRIBUTING guide, architecture doc, good-first-issues | A contributor can land a PR from the docs alone | todo |
| A5 | No security review | Dependency audit in CI (pip-audit), SECURITY.md, fuzz the HTML/PDF parsers with bad input | CI audit green, SECURITY.md exists | todo |

### Scale and robustness (large workloads)

| # | Weakness | Work | Done when | Status |
| --- | --- | --- | --- | --- |
| S1 | No crawling of whole sites | Polite crawler: sitemap/links, robots, per-host limits, depth/page caps | `crawl(url)` with tests | todo |
| S2 | Long batches cannot retry or resume | Batch API with retries (backoff), on-disk progress, resume after a crash | 10k-URL batch survives a restart | todo |
| S3 | No caching | HTTP cache with ETag/Last-Modified (conditional requests) | Re-running a batch skips unchanged pages | todo |
| S4 | Heavy memory use found on a 16 GB laptop | Profile memory; stream large PDFs page by page; cap image sizes | Peak memory per document measured and bounded | todo |
| S5 | No docs site | API reference + guides (mkdocs or similar) | Docs published | todo |

### Accuracy, measured honestly

| # | Weakness | Work | Done when | Status |
| --- | --- | --- | --- | --- |
| Q1 | Extraction only level with Trafilatura (0.902 vs 0.910) | Find and fix the remaining failure patterns; ensemble with embedded data | Held-out macro F1 above Trafilatura | todo |
| Q2 | OCR wins measured on synthetic pages only | Add real scans (license-clean or self-made photos/scans) to the OCR benchmark | Real-scan suite in bench/ | todo |
| Q3 | Never compared with Docling, Marker or paid OCR | Benchmark Docling (MIT) and Marker (bench only) and one paid OCR on a shared sample | Comparison table in bench/README.md | todo |
| Q4 | OCR: blur is the largest error; engines differ by case | Tesseract + RapidOCR cross-check / ensemble as an optional extra | Beats both single engines on held-out | todo |
| Q5 | Hard OCR suite not yet measured held-out after fixes | Final held-out run (needs free memory) | Numbers in bench/README.md | doing |
| Q6 | Search ranking v0 is hand-set | Search benchmark (license-clean, offline-reproducible), tuned ranking, cross-encoder rerank option | Ranking beats fusion-only on the benchmark | todo |
| Q7 | Search agreement (the headline feature) not built | Claim-level agreement between sources, with provenance | Contradictions flagged in SearchResponse | todo |

### Trust, compliance and evidence

| # | Weakness | Work | Done when | Status |
| --- | --- | --- | --- | --- |
| T1 | Trust score is hand-tuned, not proven | Calibrate against downstream RAG accuracy (does a higher score mean better answers?) | Calibration study and curve in bench/ | todo |
| T2 | Compliance verdict carries legal weight | Clear "evidence, not legal advice" wording everywhere it shows; conservative verdicts; tests of edge cases | Wording in models, README, CLI output | done (2026-11-22: `conditions` + `disclaimer` on ComplianceInfo, CLI note) |
| T3 | Provenance stops at blocks | Sentence-level provenance | Each sentence maps to its source span | todo |

## Review log

- **2026-11-22:** first review (scores above). Strengths: honest benchmarking with held-out
  splits, 175 tests, CI on 3 OSes, typed API; real differentiation (extraction confidence,
  PDF text-layer check, compliance evidence, provenance). Biggest gap: not installable by
  anyone. Priority: finish search agreement, then release an alpha (A1), then real-world
  and competitor benchmarks (Q2, Q3).
