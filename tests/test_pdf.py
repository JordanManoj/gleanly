from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest
import respx

from gleanly import Client, load
from gleanly.errors import UnsupportedSourceError
from gleanly.models import BlockType, Document
from gleanly.pdf import read_pdf
from gleanly.pdf.native import pdf_date

from .pdfmaker import Line, Page, build_pdf, flow

pytest.importorskip("pypdfium2")

BULLET = "•"
SITE = "https://harbour.example"


def _report_pdf() -> bytes:
    def page(n: int, paras: Sequence[tuple[str, float, bool]], extra: list[Line]) -> Page:
        lines = flow(paras) + extra
        lines.append(Line("Harbour Board - Annual Report 2025", 72, 760, 9))  # running header
        lines.append(Line(str(n), 300, 30, 9))  # page number
        return Page(lines)

    paras = [
        ("Annual Report", 22, True),
        ("Summary of the year", 15, True),
        (
            "The harbour board met eleven times this year and approved two new berths for "
            "the fishing fleet, which had been waiting since the storm.",
            11,
            False,
        ),
        ("Main decisions", 11, True),
        (f"{BULLET} Two new berths on the north quay", 11, False),
        (f"{BULLET} Dredging of the inner basin", 11, False),
        (
            "Ticket prices for visitors stay the same until the end of next year, the board con-",
            11,
            False,
        ),
    ]
    tail = Line("firmed after a long debate.", 72, flow(paras)[-1].y - 14.85, 11)
    p2 = [
        ("Finances", 15, True),
        (
            "Income rose by four per cent, mostly from mooring fees and the new fuel station.",
            11,
            False,
        ),
    ]
    return build_pdf(
        [page(1, paras, [tail]), page(2, p2, [])],
        title="Annual Report 2025",
        author="Harbour Board",
    )


def test_layout_headings_lists_hyphenation_and_running_lines() -> None:
    blocks = read_pdf(_report_pdf()).extraction.blocks
    assert [(b.type, b.level) for b in blocks if b.type == BlockType.HEADING] == [
        (BlockType.HEADING, 1),
        (BlockType.HEADING, 2),
        (BlockType.HEADING, 3),  # bold body-size line
        (BlockType.HEADING, 2),
    ]
    texts = [b.text for b in blocks]
    assert "- Two new berths on the north quay\n- Dredging of the inner basin" in texts
    assert any("the board confirmed after a long debate." in t for t in texts)
    joined = "\n".join(texts)
    assert "Harbour Board - Annual Report" not in joined  # running header learned
    assert "\n2\n" not in f"\n{joined}\n"  # page number dropped


def test_load_pdf_file_with_provenance_and_metadata(tmp_path: Path) -> None:
    path = tmp_path / "report.pdf"
    path.write_bytes(_report_pdf())
    doc = load(str(path))
    assert doc.markdown.startswith("# Annual Report\n\n## Summary of the year")
    assert doc.metadata.title == "Annual Report 2025"
    assert doc.metadata.author == "Harbour Board"
    assert doc.metadata.content_type == "application/pdf"
    assert doc.quality.extraction_method == "pdf"
    assert doc.fetch_trace.final_rung == "pdf"
    finance = next(b for b in doc.blocks if b.text == "## Finances")
    assert finance.provenance.kind == "pdf"
    assert finance.provenance.page == 2
    assert finance.provenance.bbox is not None
    x0, top, x1, bottom = finance.provenance.bbox
    assert 70 <= x0 < x1
    assert 0 < top < bottom < 120
    assert (
        doc.markdown[finance.provenance.char_start : finance.provenance.char_end] == "## Finances"
    )


def test_scanned_pages_are_reported(tmp_path: Path) -> None:
    text_page = Page(
        flow([("A page with a real text layer and enough words to count.", 11, False)])
    )
    scan = Page(image=(4, 4, bytes([255]) * 48))  # an image-only page, like a scan
    path = tmp_path / "mixed.pdf"
    path.write_bytes(build_pdf([text_page, scan]))
    doc = load(str(path))
    # A blank scan has nothing for OCR to read either, so it is reported.
    assert any("1 of 2 pages have no readable text" in w for w in doc.quality.warnings)
    full = load_single(tmp_path, text_page)
    assert doc.quality.score < full.quality.score


def load_single(tmp_path: Path, page: Page) -> Document:
    p = tmp_path / "single.pdf"
    p.write_bytes(build_pdf([page]))
    return load(str(p))


def test_broken_pdf_is_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is not really a pdf")
    with pytest.raises(UnsupportedSourceError, match="Could not open the PDF"):
        load(str(path))


@pytest.mark.parametrize("ctype", ["application/pdf", "application/octet-stream"])
async def test_pdf_from_url_with_ai_txt_rule(mock_http: respx.MockRouter, ctype: str) -> None:
    mock_http.get(f"{SITE}/robots.txt").mock(return_value=httpx.Response(404))
    mock_http.get(f"{SITE}/.well-known/tdmrep.json").mock(return_value=httpx.Response(404))
    mock_http.get(f"{SITE}/ai.txt").mock(
        return_value=httpx.Response(
            200, text="User-Agent: *\nDisallow: *.pdf\n", headers={"content-type": "text/plain"}
        )
    )
    mock_http.get(f"{SITE}/files/report").mock(
        return_value=httpx.Response(200, content=_report_pdf(), headers={"content-type": ctype})
    )
    async with Client(min_delay=0, browser="never") as client:
        doc = await client.aload(f"{SITE}/files/report")
    assert doc.blocks[0].text == "# Annual Report"
    assert doc.compliance.ai_txt_allowed is False  # "*.pdf" applies to a PDF without .pdf
    assert doc.compliance.ai_use == "disallowed"
    assert [s.rung for s in doc.fetch_trace.steps][-2:] == ["http", "pdf"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("D:20250314083000Z", "2025-03-14"), ("D:2024", "2024"), ("", None), ("garbage", None)],
)
def test_pdf_date(raw: str, expected: str | None) -> None:
    assert pdf_date(raw) == expected
