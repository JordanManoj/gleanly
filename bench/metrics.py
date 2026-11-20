"""Extraction-quality metrics.

We compare the extracted text with the ground-truth article body as bags of word
tokens: precision = share of extracted tokens that belong to the article (penalises
boilerplate), recall = share of the article that was extracted (penalises lost content).
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass

_TOKEN = re.compile(r"\w+", re.UNICODE)


def tokens(text: str) -> Counter[str]:
    return Counter(t.lower() for t in _TOKEN.findall(text))


@dataclass(frozen=True)
class Score:
    precision: float
    recall: float

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def score(extracted: str, truth: str) -> Score:
    got, want = tokens(extracted), tokens(truth)
    if not want:
        return Score(1.0 if not got else 0.0, 1.0)
    if not got:
        return Score(0.0, 0.0)
    overlap = sum((got & want).values())
    return Score(overlap / sum(got.values()), overlap / sum(want.values()))


@dataclass(frozen=True)
class Summary:
    n: int
    precision: float
    recall: float
    f1: float
    f1_median: float
    failures: int  # pages with F1 < 0.5


def summarize(scores: list[Score]) -> Summary:
    if not scores:
        return Summary(0, 0.0, 0.0, 0.0, 0.0, 0)
    f1s = [s.f1 for s in scores]
    return Summary(
        n=len(scores),
        precision=statistics.fmean(s.precision for s in scores),
        recall=statistics.fmean(s.recall for s in scores),
        f1=statistics.fmean(f1s),
        f1_median=statistics.median(f1s),
        failures=sum(f < 0.5 for f in f1s),
    )
