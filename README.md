# gleanly

**All-in-one, open-source text acquisition for AI.** Turn any URL or file into clean
Markdown with a **trust score**, **compliance metadata** ("can I use this for AI
training?") and **provenance** for every block. One `pip install`, one process, no Docker.

```python
from gleanly import load

doc = load("https://example.com/article")
print(doc.markdown)  # clean Markdown (tables and code preserved)
print(doc.quality.score)  # 0..1, comparable across web, PDF and OCR sources
print(doc.compliance.ai_use)  # "allowed" | "disallowed" | "unclear", with evidence
print(doc.blocks[0].provenance)  # URL + XPath + character span in the Markdown
print(doc.fetch_trace.steps)  # every fetch-ladder step that was tried, and why
```

Async: `doc = await aload(url)`. Batch with shared rate limits: `async with Client() as c: ...`

CLI:

```bash
gleanly load https://example.com/article -o article.md
gleanly load https://example.com/article -o article.json   # full Document as JSON
```

## PDFs, scans and images

```bash
pip install "gleanly[pdf]"   # native PDFs
pip install "gleanly[ocr]"   # + OCR; also install Tesseract (github.com/tesseract-ocr/tesseract)
```

```python
doc = load("report.pdf")  # or "scan.jpg", or a URL serving either
doc.blocks[3].provenance  # kind="pdf" (text layer) or "image" (OCR), page, bbox
doc.quality.ocr_confidence  # Tesseract's word confidence, when OCR was used
doc.quality.extraction_confidence  # PDFs: agreement between the text layer and OCR
```

What gleanly adds on top of plain PDF text extraction and Tesseract:

- Headings, lists and re-joined hyphenation; running headers, footers and page numbers
  learned across pages and removed.
- Scanned pages inside a PDF are OCR'd automatically.
- **Text-layer check:** pages whose hidden text looks broken, plus a small sample, are
  compared with OCR; a layer that does not match the page (a wrong font map, a poor old
  OCR layer) is replaced and the page is named in a warning.
- OCR clean-up tuned on a benchmark: 0.77% characters wrong on held-out pages against
  16.1% for plain Tesseract, mostly by fixing shadows, faint print and phone photos
  ([bench/README.md](bench/README.md)).

## Search

```python
from gleanly import search

resp = search("tide pool animals")  # Wikipedia by default; Brave/SearXNG when configured
for r in resp.results:
    print(r.score, r.hit.url, r.hit.engines)  # which engines found it, and at what rank
    print(r.document.quality.score, r.document.compliance.ai_use)  # every result is a full Document
```

```bash
gleanly search "tide pool animals" -n 5 --exclude-disallowed
```

Backends use official APIs only: Wikipedia (no key), Brave Search (`BRAVE_API_KEY`) and
your own SearXNG instance (`SEARXNG_URL`). Results from several engines are merged with
reciprocal rank fusion, then every page is fetched through `load()` (robots.txt, rate
limits, trust score, AI-use verdict, provenance). Ranking v0 combines query relevance,
the fused rank and the page's trust score; it will be tuned on a search benchmark.

## Status

Phases 1 (web pages) and 2 (PDFs and OCR) are done; Phase 3 (search) is in progress. See
[docs/status.md](docs/status.md).

| Capability | Status |
| --- | --- |
| Web page → Markdown + metadata | ✅ v0 |
| Fetch ladder: HTTP → embedded data (JSON-LD, `__NEXT_DATA__`) → Playwright | ✅ v0 |
| robots.txt (RFC 9309), per-host rate limiting, honest User-Agent | ✅ |
| Compliance: TDMRep, `ai.txt`, `noai`, AI-crawler opt-outs, license detection, PII flags | ✅ v0 |
| Quality report + trust score | ✅ v0 (uncalibrated) |
| Native PDFs (`gleanly[pdf]`): headings, lists, page + bounding-box provenance, running headers removed | ✅ v0 |
| OCR for images and scanned PDF pages (`gleanly[ocr]` + Tesseract): background flattening, text-size normalisation, layout self-check, OCR confidence in the trust score | ✅ v0 |
| `search()` with reranking and cross-source agreement | Phase 3 |
| Archive fallbacks, crawling, server mode, benchmark | Phase 4 |

## Ethics by design

The library identifies itself honestly (`gleanly/<version> (+project URL)`), respects
robots.txt by default, rate-limits per host and never tries to evade blocks: no fingerprint
spoofing, CAPTCHA solving or proxy rotation. When a site refuses access, you get a clear
explanation in `FetchError.trace`.

## Install (development)

```bash
uv sync                       # core + dev tools
uv run pytest
uv sync --extra browser && uv run playwright install chromium   # optional rung 3
```

## License

Apache-2.0
