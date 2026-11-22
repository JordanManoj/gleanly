# Architecture

gleanly turns any source (web page, file, PDF, image, search query) into the same typed
`Document`: clean Markdown, blocks with provenance, metadata, a quality report with a
trust score, compliance evidence and a fetch trace. Everything runs in one process.

## The path of a `load()` call

```
load(source)                         loader.py      sync wrapper around aload()
  Client.aload                       client.py      orchestration; one per batch
    ├─ local file  ──────────────────────────────── .html / .pdf / images / .txt / .md
    └─ URL
        ├─ robots.txt, TDMRep, ai.txt  fetch/robots.py, compliance/tdmrep.py, aitxt.py
        ├─ rung 1: HTTP              fetch/http.py   honest User-Agent, size cap, charset
        ├─ PDF?  → pdf/native.py     text layer, layout; OCR for scans; text-layer check
        ├─ image? → ocr/engine.py    clean-up + Tesseract
        ├─ HTML → clean/html.py      main-content extraction → blocks with XPath
        ├─ rung 2: fetch/embedded.py JSON-LD / __NEXT_DATA__ when the visible text is poor
        └─ rung 3: fetch/browser.py  Playwright, only when the page looks JS-rendered
    _build
        ├─ quality/crosscheck.py     independent second extractor → confidence
        ├─ compliance/assess.py      robots, TDMRep, ai.txt, noai, license, PII → verdict
        ├─ quality/__init__.py       signals → trust score + warnings
        └─ assemble                  Markdown + Block provenance (char spans)
```

`search(query)` (search/) queries backends in parallel, fuses their result lists with
reciprocal rank fusion and fetches every hit through the same `Client.aload`, so each
search result is a full `Document`.

## Packages

| Package | Responsibility |
| --- | --- |
| `fetch/` | Getting bytes ethically: HTTP, robots.txt, per-host rate limits, embedded data, browser, routing heuristics |
| `clean/` | HTML → blocks: main-content extraction (`html.py`), the independent block classifier (`blocks.py`), comments, metadata |
| `pdf/` | PDF text layer, the shared words → lines → paragraphs layout (`layout.py`, also used by OCR), text-layer check |
| `ocr/` | Image clean-up and the Tesseract wrapper (TSV output: words, boxes, confidences) |
| `quality/` | Cross-check confidence and the trust score |
| `compliance/` | Every AI-use signal and the verdict with conditions |
| `search/` | Backends (official APIs only), fusion, ranking |
| `models.py` | The public, typed output models (Pydantic v2) |

## Design rules

- **Every method reports its confidence, and independent methods check each other.**
  The block classifier checks the main extractor; OCR checks PDF text layers; several
  search engines check each other's rankings.
- **Benchmark first.** A change to extraction, OCR or ranking is kept only if it improves
  the held-out split of the relevant benchmark in `bench/`; what was tried and dropped is
  written down in `bench/README.md`.
- **Ethical fetching.** Honest User-Agent, robots.txt respected by default, rate limits,
  no evasion. When blocked, say so clearly.
- **Light core.** Heavy dependencies are optional extras (`[browser]`, `[pdf]`, `[ocr]`).
- **No real network in unit tests.** HTTP is mocked with respx; test documents are
  generated or written for the tests (`tests/pdfmaker.py`, `tests/fixtures/`).
