"""Command line: ``gleanly load URL -o out.md``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from gleanly.__about__ import __version__
from gleanly.errors import AcquisitionError, FetchError
from gleanly.loader import load


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gleanly", description="Turn URLs and files into clean, AI-ready Markdown."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("load", help="Load a URL or local file.")
    p.add_argument("source", help="URL or path to a local .html/.txt/.md file")
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
        "--ignore-robots",
        action="store_true",
        help="Fetch even if robots.txt disallows it. Only use with the site owner's permission.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")

    fmt = args.format or ("json" if (args.output or "").endswith(".json") else "md")
    try:
        doc = load(
            args.source,
            browser=args.browser,
            timeout=args.timeout,
            min_delay=args.min_delay,
            respect_robots=not args.ignore_robots,
            include_comments=args.comments,
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
    for warning in q.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
