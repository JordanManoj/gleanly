from __future__ import annotations

from pathlib import Path

import pytest

from bench.extractors import gleanly_extract
from bench.metrics import Score, score, summarize

from .conftest import fixture_text


def test_perfect_and_empty() -> None:
    assert score("The cat sat.", "the CAT sat").f1 == 1.0
    assert score("", "some text").f1 == 0.0
    assert score("", "").precision == 1.0


def test_boilerplate_lowers_precision_not_recall() -> None:
    s = score("menu home login the cat sat", "the cat sat")
    assert s.recall == 1.0
    assert s.precision == pytest.approx(0.5)


def test_lost_content_lowers_recall() -> None:
    s = score("the cat", "the cat sat down")
    assert s.precision == 1.0
    assert s.recall == pytest.approx(0.5)


def test_repeated_tokens_count_as_multiset() -> None:
    assert score("the the the", "the").precision == pytest.approx(1 / 3)


def test_summarize() -> None:
    summary = summarize([Score(1.0, 1.0), Score(0.2, 0.2)])
    assert summary.n == 2
    assert summary.f1 == pytest.approx(0.6)
    assert summary.failures == 1
    assert summarize([]).n == 0


def test_gleanly_adapter_on_fixture() -> None:
    text = gleanly_extract(fixture_text("article.html"), "https://fieldnotes.example/")
    assert "Tide pools are rocky depressions" in text
    assert "cookies" not in text
    assert "#" not in text  # plain text, not Markdown


def test_confidence_rank_statistics() -> None:
    from bench.confidence import auroc, ranks, spearman

    assert ranks([3.0, 1.0, 1.0]) == [2.0, 0.5, 0.5]
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert auroc([0.1, 0.2, 0.9, 0.8], [True, True, False, False]) == 1.0
    assert auroc([0.5, 0.5], [True, False]) == 0.5


def test_wceb_site_groups_and_registry() -> None:
    from bench.datasets import DATASETS, GROUPS, site_of

    assert site_of("BBC_13") == "bbc"
    assert site_of("nytimes_68") == "nytimes"
    assert site_of("blogs.wsj.com_brussels_01") == "blogs.wsj.com_brussels"
    assert site_of("272") is None
    assert all(name in DATASETS for name in GROUPS["wceb"])
    assert "wceb-scrapinghub" not in DATASETS  # same pages as scrapinghub-aeb


def test_wceb_pages_read_from_local_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    import bench.datasets as d

    monkeypatch.setattr(d, "DATA_DIR", tmp_path)
    root = tmp_path / "wceb"
    (root / "html" / "cetd").mkdir(parents=True)
    (root / "ground-truth").mkdir()
    rows = [
        {"page_id": "a1", "plaintext": "Hello world", "source": ["cetd", "BBC_1"]},
        {"page_id": "b2", "plaintext": "  ", "source": ["cetd", "BBC_2"]},  # empty: skipped
    ]
    (root / "ground-truth" / "cetd.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    for r in rows:
        (root / "html" / "cetd" / f"{r['page_id']}.html").write_bytes(
            b'<html><head><meta charset="windows-1252"></head><body>caf\xe9</body></html>'
        )
    got = list(d.pages(d.WCEB["cetd"]))
    assert [p.id for p in got] == ["a1"]
    assert got[0].site == "bbc"
    assert "café" in got[0].html
