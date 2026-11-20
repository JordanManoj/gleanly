"""Run the extraction benchmark.

uv sync --group bench
uv run python -m bench.run                 # all extractors, the Scrapinghub article set
uv run python -m bench.run -d wceb         # the seven WCEB datasets, one table each + overview
uv run python -m bench.run --limit 20 -e gleanly --worst 10
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from bench.datasets import DATASETS, GROUPS, SCRAPINGHUB, Dataset, pages
from bench.extractors import Extractor, available
from bench.metrics import Score, Summary, score, summarize

RESULTS_DIR = Path(__file__).parent / "results"


def run_dataset(
    ds: Dataset,
    extractors: dict[str, Extractor],
    *,
    limit: int | None,
    split: str,
    worst: int,
) -> tuple[int, dict[str, Summary], dict[str, dict[str, Score]], dict[str, float]]:
    data = list(pages(ds, limit, split))  # type: ignore[arg-type]
    per_page: dict[str, dict[str, Score]] = {name: {} for name in extractors}
    timings: dict[str, float] = dict.fromkeys(extractors, 0.0)
    for page in data:
        for name, fn in extractors.items():
            t0 = time.perf_counter()
            try:
                text = fn(page.html, page.url)
            except Exception as exc:  # a crash counts as an empty extraction
                print(f"  {name} crashed on {page.id}: {type(exc).__name__}: {exc}")
                text = ""
            timings[name] += time.perf_counter() - t0
            per_page[name][page.id] = score(text, page.truth)

    print(f"\n{ds.name}: {ds.description}: {len(data)} pages\n")
    header = f"{'extractor':<16} {'F1':>6} {'median':>7} {'prec':>6} {'recall':>7} {'F1<0.5':>7} {'ms/page':>8}"  # noqa: E501
    print(header)
    print("-" * len(header))
    summaries: dict[str, Summary] = {}
    ms_per_page: dict[str, float] = {}
    for name, scores in per_page.items():
        s = summarize(list(scores.values()))
        summaries[name] = s
        ms_per_page[name] = 1000 * timings[name] / max(1, len(data))
        print(
            f"{name:<16} {s.f1:>6.3f} {s.f1_median:>7.3f} {s.precision:>6.3f} "
            f"{s.recall:>7.3f} {s.failures:>7} {ms_per_page[name]:>8.1f}"
        )
    if worst:
        for name, scores in per_page.items():
            print(f"\nWorst pages for {name}:")
            ranked = sorted(scores.items(), key=lambda kv: kv[1].f1)[:worst]
            for pid, sc in ranked:
                print(f"  {pid}  F1 {sc.f1:.3f}  P {sc.precision:.3f}  R {sc.recall:.3f}")
    return len(data), summaries, per_page, ms_per_page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench.run")
    parser.add_argument(
        "-d",
        "--dataset",
        default=SCRAPINGHUB.name,
        choices=sorted(DATASETS) + sorted(GROUPS),
        help="A dataset, or a group such as 'wceb'.",
    )
    parser.add_argument("-e", "--extractors", help="Comma-separated subset to run.")
    parser.add_argument("--limit", type=int, help="Only the first N pages per dataset.")
    parser.add_argument(
        "--split",
        default="all",
        choices=["all", "dev", "test"],
        help="dev = tuning pages, test = held-out pages (report these).",
    )
    parser.add_argument(
        "--worst", type=int, default=0, help="List the N worst pages per extractor."
    )
    parser.add_argument("--save", action="store_true", help="Write results to bench/results/.")
    args = parser.parse_args(argv)

    extractors = available()
    if args.extractors:
        wanted = args.extractors.split(",")
        missing = [w for w in wanted if w not in extractors]
        if missing:
            parser.error(f"not installed: {', '.join(missing)} (run `uv sync --group bench`)")
        extractors = {k: v for k, v in extractors.items() if k in wanted}

    names = GROUPS.get(args.dataset, [args.dataset])
    results = {}
    for name in names:
        ds = DATASETS[name]
        n, summaries, per_page, ms = run_dataset(
            ds, extractors, limit=args.limit, split=args.split, worst=args.worst
        )
        results[name] = (n, summaries, per_page, ms)

    if len(names) > 1:
        print(f"\nOverview (mean F1 per dataset, split={args.split})\n")
        header = f"{'dataset':<26}{'pages':>6}" + "".join(f"{e:>18}" for e in extractors)
        print(header)
        print("-" * len(header))
        for name, (n, summaries, _, _) in results.items():
            cells = "".join(f"{summaries[e].f1:>18.3f}" for e in extractors)
            print(f"{name:<26}{n:>6}{cells}")
        macro = "".join(
            f"{statistics.fmean(r[1][e].f1 for r in results.values()):>18.3f}" for e in extractors
        )
        print(f"{'macro average':<26}{'':>6}{macro}")

    if args.save:
        RESULTS_DIR.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out = RESULTS_DIR / f"{args.dataset}-{args.split}-{stamp}.json"
        out.write_text(
            json.dumps(
                {
                    name: {
                        "pages": n,
                        "summary": {k: vars(v) for k, v in summaries.items()},
                        "ms_per_page": ms,
                        "per_page": {
                            k: {
                                pid: {"p": s.precision, "r": s.recall, "f1": s.f1}
                                for pid, s in v.items()
                            }
                            for k, v in per_page.items()
                        },
                    }
                    for name, (n, summaries, per_page, ms) in results.items()
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"\nSaved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
