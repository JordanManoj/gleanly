# Contributing to gleanly

Thanks for helping. This guide gets you from a fresh clone to a merged change.

## Set up

```bash
git clone https://github.com/JordanManoj/gleanly.git
cd gleanly
uv sync --all-extras --all-groups   # installs dev tools, the [pdf]/[ocr]/[browser] extras and bench baselines
```

OCR tests also need the [Tesseract](https://github.com/tesseract-ocr/tesseract) program;
without it they are skipped.

## Before you open a pull request

```bash
uv run ruff format .        # formatting (also checks code examples in Markdown)
uv run ruff check .         # lint
uv run pyright              # types
uv run pytest               # tests (no real network: HTTP is mocked)
```

CI runs the same checks on Linux, macOS and Windows with Python 3.10-3.13.

## What a good change looks like

- **One topic per pull request**, with tests. Unit tests never touch the real network:
  mock HTTP with `respx`, and generate test documents (see `tests/pdfmaker.py`).
- **Accuracy changes come with numbers.** If you change extraction, OCR or ranking, run
  the matching benchmark (`bench/`), tune only on the `dev` split and report the `test`
  split in the pull request. Changes that do not beat the current results on `test` are
  not merged; record them under "tried and dropped" in `bench/README.md` instead.
- **New dependencies** must have a permissive license (MIT, BSD, Apache-2.0, ...), be
  listed in `docs/dependencies.md`, and go into an optional extra if they are heavy.
- **Ethical fetching** is not negotiable: no anti-bot evasion, honest User-Agent,
  robots.txt respected by default.
- Update `CHANGELOG.md` under "Unreleased".

## Where things are

See [docs/architecture.md](docs/architecture.md) for how a `load()` call flows through the
code, and [docs/roadmap.md](docs/roadmap.md) and [docs/review.md](docs/review.md) for what
is planned and the known weaknesses (good places to start).

## Reporting bugs

Open an issue with the gleanly version, the source (URL or a small file) and what you
expected. Security problems: see [SECURITY.md](SECURITY.md).
