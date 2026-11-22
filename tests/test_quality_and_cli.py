from __future__ import annotations

import json
from pathlib import Path

import pytest

from gleanly.clean.html import Extraction, RawBlock
from gleanly.cli import main
from gleanly.models import BlockType
from gleanly.quality import compute_quality

from .conftest import FIXTURES


def _extraction(words: int, *, links: float = 0.0, paragraphs: int = 5) -> Extraction:
    per = max(1, words // paragraphs)
    blocks = [RawBlock(BlockType.HEADING, "# Title", None, 1)]
    blocks += [
        RawBlock(BlockType.PARAGRAPH, " ".join(["word"] * per), None) for _ in range(paragraphs)
    ]
    ex = Extraction(blocks, "http")
    ex.link_chars = int(ex.content_chars * links)
    ex.page_chars = ex.content_chars * 2
    return ex


def test_good_article_scores_high() -> None:
    q = compute_quality(_extraction(600), raw_size=20_000)
    assert q.score > 0.9
    assert q.warnings == []
    assert q.boilerplate_ratio == pytest.approx(0.5)


def test_score_is_monotonic_in_length() -> None:
    scores = [compute_quality(_extraction(n), raw_size=10_000).score for n in (10, 50, 200, 800)]
    assert scores == sorted(scores)


def test_penalties_and_warnings() -> None:
    linky = compute_quality(_extraction(300, links=0.8), raw_size=10_000)
    assert any("link text" in w for w in linky.warnings)
    assert linky.score < compute_quality(_extraction(300), raw_size=10_000).score

    truncated = compute_quality(_extraction(300), raw_size=10_000, truncated=True)
    assert any("truncated" in w for w in truncated.warnings)

    js = compute_quality(_extraction(10), raw_size=10_000, js_suspect=True)
    assert any("[browser] extra" in w for w in js.warnings)

    empty = compute_quality(Extraction([], "http"), raw_size=10_000)
    assert empty.score == 0.0


# ---------------------------------------------------------------- CLI


def test_cli_markdown_to_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out.md"
    assert main(["load", str(FIXTURES / "article.html"), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Understanding Tide Pools")
    assert "quality" in capsys.readouterr().err


def test_cli_json_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["load", str(FIXTURES / "article.html"), "-f", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["metadata"]["title"] == "Understanding Tide Pools"
    assert data["compliance"]["ai_use"] == "allowed"


def test_cli_error_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["load", "not a source at all"]) == 1
    assert "error:" in capsys.readouterr().err


def test_cli_no_ocr_reports_scanned_pdf_pages(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("pypdfium2")
    from .pdfmaker import Page, build_pdf, flow

    pdf = tmp_path / "mixed.pdf"
    text = Page(flow([("A cover page with a real text layer for the CLI test.", 11, False)]))
    pdf.write_bytes(build_pdf([text, Page(image=(4, 4, bytes([255]) * 48))]))
    assert main(["load", str(pdf), "--no-ocr", "-f", "json"]) == 0
    out = capsys.readouterr().out
    assert "OCR was not available: ocr='never'" in out


def test_python_dash_m_runs_the_cli() -> None:
    import subprocess
    import sys

    from gleanly import __version__

    out = subprocess.run(
        [sys.executable, "-m", "gleanly", "--version"], capture_output=True, text=True, check=True
    )
    assert __version__ in out.stdout
