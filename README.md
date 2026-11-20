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

## Status

Phase 1 (web pages) is in progress. See [docs/status.md](docs/status.md).

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
