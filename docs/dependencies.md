# Dependencies and licenses

The project is Apache-2.0. Only permissively licensed dependencies are allowed in the core;
no GPL/AGPL. Check the license **before** adding a dependency and record it here.

## Core (`pip install gleanly`)

| Package | License | Why |
| --- | --- | --- |
| [httpx](https://github.com/encode/httpx) | BSD-3-Clause | Async/sync HTTP client (rung 1, robots.txt, TDMRep) |
| [pydantic](https://github.com/pydantic/pydantic) | MIT | Typed public output models |
| [lxml](https://github.com/lxml/lxml) | BSD-3-Clause | HTML parsing, XPath provenance |
| [protego](https://github.com/scrapy/protego) | BSD-3-Clause | RFC 9309 robots.txt parsing |

Transitive: anyio (MIT), httpcore (BSD-3-Clause), h11 (MIT), idna (BSD-3-Clause),
pydantic-core (MIT), annotated-types (MIT), typing-inspection (MIT),
typing-extensions (PSF-2.0), **certifi (MPL-2.0)**.

> certifi is MPL-2.0, a weak, file-level copyleft. We use it unmodified as a separate
> package (via httpx), which is compatible with distributing this project under Apache-2.0.

## Optional extras

| Extra | Package | License |
| --- | --- | --- |
| `browser` | [playwright](https://github.com/microsoft/playwright-python) | Apache-2.0 |
| `browser` | greenlet (transitive) | MIT / PSF-2.0 |
| `pdf`, `ocr` | [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | BSD-3-Clause / Apache-2.0 (bundles PDFium: BSD-3-Clause) |
| `ocr` | [Pillow](https://github.com/python-pillow/Pillow) | MIT-CMU |
| `ocr` | [glyphly](https://github.com/JordanManoj/glyphly) | Apache-2.0 (models: PaddleOCR, Apache-2.0) |
| `ocr` | numpy, onnxruntime (via glyphly) | BSD-3-Clause, MIT |

The [Tesseract](https://github.com/tesseract-ocr/tesseract) program (Apache-2.0) is
optional: with `ocr_engine="tesseract"` (or when glyphly is missing) gleanly calls it
directly (no Python binding) and reads per-word confidences and boxes from its TSV output.
`search` and `llm` extras arrive in later phases.

## Development only (not shipped)

| Package | License |
| --- | --- |
| pytest | MIT |
| pytest-asyncio | Apache-2.0 |
| respx | BSD-3-Clause |
| ruff | MIT |
| pyright | MIT |

## Benchmark only (`uv sync --group bench`, not shipped)

Baseline extractors we compare against in `bench/`. They are never imported by the
`gleanly` package.

| Package | License |
| --- | --- |
| trafilatura | Apache-2.0 |
| readability-lxml | Apache-2.0 |

Transitive: courlan, htmldate, tzdata (Apache-2.0); justext (BSD-2-Clause); dateparser,
lxml-html-clean, python-dateutil, cssselect (BSD); charset-normalizer, urllib3, pytz,
tzlocal (MIT); regex (Apache-2.0 AND CNRI-Python); **chardet (LGPL-2.1+)**.

> chardet is LGPL and arrives via readability-lxml. That is acceptable only because the
> `bench` group is a local development tool that is never distributed with gleanly. Do not
> add readability-lxml (or chardet) to the core or to any extra.

Benchmark data: the Zyte/Scrapinghub article-extraction-benchmark (MIT annotations). The
pages themselves are third-party content: downloaded into `bench/data/` on demand and
never committed.

Also the Web Content Extraction Benchmark (chatnoir-eu/web-content-extraction-benchmark;
code Apache-2.0, no separate data license stated): downloaded into `bench/data/wceb/` for
local evaluation only, never committed or redistributed.

Last checked: 2026-11-20.
