"""Command line: ``gleanly load URL -o out.md`` and ``gleanly search "query"``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from gleanly.__about__ import __version__
from gleanly.errors import AcquisitionError, FetchError
from gleanly.loader import load
from gleanly.models import SearchResponse


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gleanly", description="Turn URLs and files into clean, AI-ready Markdown."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("load", help="Load a URL or local file.")
    p.add_argument(
        "source", help="URL or local file: .html, .pdf, images (.png/.jpg/.tiff...), .txt, .md"
    )
    p.add_argument("-o", "--output", help="Write to this file instead of stdout.")
    p.add_argument(
        "-f",
        "--format",
        choices=["md", "json"],
        help="md: Markdown only; json: full Document (default: from -o extension, else md).",
    )
    p.add_argument("--browser", choices=["auto", "never", "always"], default="auto")
    p.add_argument("--timeout", type=float, default=20.0, help="Seconds per request.")
    p.add_argument("--min-delay", type=float, default=1.0, help="Seconds between requests/host.")
    p.add_argument(
        "--comments",
        action="store_true",
        help="Also extract reader comments (appended after the main content).",
    )
    p.add_argument(
        "--no-ocr",
        action="store_true",
        help="Do not OCR images or scanned PDF pages (they are reported instead).",
    )
    p.add_argument(
        "--ocr-engine",
        choices=["auto", "glyphly", "tesseract"],
        default="auto",
        help="auto: glyphly if installed, else Tesseract (default: auto).",
    )
    p.add_argument(
        "--ocr-lang",
        default="eng",
        help="Tesseract language(s), e.g. eng or eng+deu (default: eng).",
    )
    p.add_argument(
        "--ignore-robots",
        action="store_true",
        help="Fetch even if robots.txt disallows it. Only use with the site owner's permission.",
    )

    s = sub.add_parser("search", help="Search the web; every result is fetched and scored.")
    s.add_argument("query")
    s.add_argument("-n", "--max-results", type=int, default=5)
    s.add_argument(
        "-b",
        "--backend",
        action="append",
        choices=["wikipedia", "brave", "searxng"],
        help="Repeat to use several (default: every backend configured here).",
    )
    s.add_argument(
        "--exclude-disallowed", action="store_true", help="Drop pages whose AI use is disallowed."
    )
    s.add_argument("--no-fetch", action="store_true", help="Only list hits; do not fetch pages.")
    s.add_argument("-f", "--format", choices=["md", "json"], default="md")
    s.add_argument("-o", "--output", help="Write to this file instead of stdout.")
    return parser


def _search_markdown(resp: SearchResponse) -> str:
    lines = [f"# Search: {resp.query}", ""]
    for i, r in enumerate(resp.results, 1):
        title = (r.document.metadata.title if r.document else None) or r.hit.title or r.hit.url
        lines.append(f"## {i}. {title}")
        lines.append(f"<{r.hit.url}>")
        found_by = ", ".join(f"{e} #{r.hit.ranks[e]}" for e in r.hit.engines)
        facts = [f"score {r.score:.2f}", f"found by {found_by}"]
        if r.document is not None:
            q, c = r.document.quality, r.document.compliance
            facts += [f"trust {q.score:.2f}", f"AI use: {c.ai_use}"]
        elif r.error:
            facts.append(f"not fetched: {r.error}")
        lines.append(" | ".join(facts))
        if r.hit.snippet:
            lines.append(f"> {r.hit.snippet}")
        lines.append("")
    return "\n".join(lines)


def _run_search(args: argparse.Namespace) -> int:
    from gleanly.search import search

    resp = search(
        args.query,
        backends=args.backend,
        max_results=args.max_results,
        fetch=not args.no_fetch,
        exclude_disallowed=args.exclude_disallowed,
    )
    out = resp.model_dump_json(indent=2) if args.format == "json" else _search_markdown(resp)
    if args.output:
        Path(args.output).write_text(out + "\n", encoding="utf-8")
    else:
        sys.stdout.write(out + "\n")
    print(
        f"{len(resp.results)} results from {', '.join(resp.backends) or 'no backend'}",
        file=sys.stderr,
    )
    for warning in resp.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0 if resp.backends else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")

    if args.command == "search":
        return _run_search(args)

    fmt = args.format or ("json" if (args.output or "").endswith(".json") else "md")
    try:
        doc = load(
            args.source,
            browser=args.browser,
            timeout=args.timeout,
            min_delay=args.min_delay,
            respect_robots=not args.ignore_robots,
            include_comments=args.comments,
            ocr="never" if args.no_ocr else "auto",
            ocr_lang=args.ocr_lang,
            ocr_engine=args.ocr_engine,
        )
    except AcquisitionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if isinstance(exc, FetchError) and exc.trace is not None:
            for step in exc.trace.steps:
                mark = "ok " if step.ok else "ERR"
                print(
                    f"  [{mark}] {step.rung:<8} {step.url or ''} {step.detail or ''}",
                    file=sys.stderr,
                )
        return 1

    out = doc.model_dump_json(indent=2) if fmt == "json" else doc.markdown + "\n"
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    q, c = doc.quality, doc.compliance
    print(
        f"{doc.url}: {q.word_count} words via {q.extraction_method}, quality {q.score:.2f}, "
        f"ai_use={c.ai_use}" + (f" -> {args.output}" if args.output else ""),
        file=sys.stderr,
    )
    for condition in c.conditions:
        print(f"condition: {condition}", file=sys.stderr)
    print("note: the ai_use verdict is evidence, not legal advice.", file=sys.stderr)
    for warning in q.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
