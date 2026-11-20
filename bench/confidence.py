"""Does gleanly's extraction confidence predict extraction accuracy?

uv run python -m bench.confidence --split dev

A useful confidence ranks pages by accuracy (Spearman correlation with F1) and
separates failed extractions from good ones (AUROC for detecting F1 < 0.9).
"""

from __future__ import annotations

import argparse
import statistics

from bench.datasets import DATASETS, GROUPS, SCRAPINGHUB, pages
from bench.extractors import gleanly_pipeline
from bench.metrics import score
from gleanly.clean import markdown_to_plain
from gleanly.quality.crosscheck import LOW_CONFIDENCE, cross_check

BAD_F1 = 0.9


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):  # average ranks for ties
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2
        i = j + 1
    return out


def spearman(xs: list[float], ys: list[float]) -> float:
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    var = sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)
    return cov / var**0.5 if var else 0.0


def auroc(confidence: list[float], bad: list[bool]) -> float:
    """Probability that a good page gets higher confidence than a failed one."""
    pos = [c for c, b in zip(confidence, bad, strict=True) if b]
    neg = [c for c, b in zip(confidence, bad, strict=True) if not b]
    if not pos or not neg:
        return float("nan")
    wins = sum(1.0 if n > p else 0.5 if n == p else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def collect(dataset: str, split: str) -> tuple[list[float], list[float], int]:
    """(F1s, confidences, pages without a confidence) for one dataset."""
    f1s: list[float] = []
    confs: list[float] = []
    unknown = 0
    for page in pages(DATASETS[dataset], split=split):  # type: ignore[arg-type]
        extraction, root = gleanly_pipeline(page.html, page.url)
        text = "\n".join(markdown_to_plain(b.text) for b in extraction.blocks)
        check = cross_check(extraction, root)
        if check.confidence is None:
            unknown += 1
            continue
        f1s.append(score(text, page.truth).f1)
        confs.append(check.confidence)
    return f1s, confs, unknown


def flagged(f1s: list[float], confs: list[float]) -> tuple[float, float, float]:
    """(share of pages flagged, mean F1 flagged, mean F1 not flagged)."""
    low = [f for f, c in zip(f1s, confs, strict=True) if c < LOW_CONFIDENCE]
    high = [f for f, c in zip(f1s, confs, strict=True) if c >= LOW_CONFIDENCE]
    mean = lambda xs: statistics.fmean(xs) if xs else float("nan")  # noqa: E731
    return len(low) / max(len(f1s), 1), mean(low), mean(high)


def report(f1s: list[float], confs: list[float], unknown: int) -> None:
    bad = [f < BAD_F1 for f in f1s]
    print(f"{len(f1s)} pages with a confidence ({unknown} unknown), {sum(bad)} with F1 < {BAD_F1}")
    print(f"Spearman(confidence, F1) {spearman(confs, f1s):.3f}")
    print(f"AUROC for spotting F1 < {BAD_F1}: {auroc(confs, bad):.3f}")
    order = sorted(range(len(f1s)), key=lambda i: confs[i])
    q = len(order) // 4
    if q:
        print("Confidence quartile -> mean F1 (min F1):")
        for n in range(4):
            idx = order[n * q : (n + 1) * q if n < 3 else None]
            print(
                f"  Q{n + 1} conf {min(confs[i] for i in idx):.2f}-{max(confs[i] for i in idx):.2f}"
                f"  F1 {statistics.fmean(f1s[i] for i in idx):.3f}"
                f" ({min(f1s[i] for i in idx):.2f})"
            )
    share, low, high = flagged(f1s, confs)
    print(f"flagged (confidence < {LOW_CONFIDENCE}): {share:.0%} of pages, mean F1 {low:.3f}")
    print(f"not flagged: mean F1 {high:.3f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench.confidence")
    parser.add_argument(
        "-d", "--dataset", default=SCRAPINGHUB.name, choices=sorted([*DATASETS, *GROUPS])
    )
    parser.add_argument("--split", default="all", choices=["all", "dev", "test"])
    args = parser.parse_args(argv)

    names = GROUPS.get(args.dataset, [args.dataset])
    if len(names) == 1:
        report(*collect(names[0], args.split))
        return 0

    all_f1: list[float] = []
    all_conf: list[float] = []
    all_unknown = 0
    print(
        f"{'dataset':26} {'pages':>5} {'spear':>6} {'auroc':>6} {'flag%':>6}"
        f" {'F1 flag':>8} {'F1 rest':>8}"
    )
    for name in names:
        f1s, confs, unknown = collect(name, args.split)
        all_f1 += f1s
        all_conf += confs
        all_unknown += unknown
        bad = [f < BAD_F1 for f in f1s]
        share, low, high = flagged(f1s, confs)
        print(
            f"{name:26} {len(f1s):5} {spearman(confs, f1s):6.3f} {auroc(confs, bad):6.3f}"
            f" {share:6.0%} {low:8.3f} {high:8.3f}"
        )
    print("\nAll pages pooled:")
    report(all_f1, all_conf, all_unknown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
