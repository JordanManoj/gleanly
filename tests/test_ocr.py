"""OCR tests. They need Pillow and the Tesseract program, and are skipped without them."""

from __future__ import annotations

from pathlib import Path

import pytest

from gleanly import load
from gleanly.errors import UnsupportedSourceError
from gleanly.ocr.tesseract import parse_tsv

from .pdfmaker import Line, Page, build_pdf, flow

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageChops, ImageDraw, ImageFont  # noqa: E402

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "4\t1\t1\t1\t1\t0\t10\t20\t300\t40\t-1\t\n"
    "5\t1\t1\t1\t1\t1\t10\t22\t120\t36\t96.5\tHarbour\n"
    "5\t1\t1\t1\t1\t2\t140\t22\t100\t36\t91.0\tboard\n"
    "5\t1\t1\t1\t1\t3\t250\t22\t10\t36\t-1\t \n"
    "4\t1\t1\t1\t2\t0\t10\t70\t200\t40\t-1\t\n"
    "5\t1\t1\t1\t2\t1\t10\t72\t200\t36\t40.0\tminutes\n"
)


def test_parse_tsv_words_lines_and_scale() -> None:
    words = parse_tsv(TSV, scale=0.5)
    assert [w.text for w in words] == ["Harbour", "board", "minutes"]
    assert [w.line_end for w in words] == [False, True, True]
    assert words[0].conf == pytest.approx(0.965)
    assert words[0].x0 == 5.0  # scaled to output units
    assert words[0].size == 20.0  # line height, scaled


def _tesseract_or_skip() -> None:
    from gleanly.ocr.tesseract import find_tesseract

    try:
        find_tesseract()
    except UnsupportedSourceError:
        pytest.skip("Tesseract is not installed")


def _font(px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf", "Arial.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(size=px)


def _page_image(shadow: bool = False) -> Image.Image:
    img = Image.new("L", (1600, 700), 255)
    d = ImageDraw.Draw(img)
    d.text((80, 60), "Harbour Report", font=_font(70), fill=0)
    body = [
        "The board met eleven times this year and approved",
        "two new berths for the fishing fleet in the north.",
        "Income rose by four per cent, mostly from fees.",
    ]
    for i, line in enumerate(body):
        d.text((80, 220 + i * 70), line, font=_font(44), fill=0)
    if shadow:  # faint grey print on paper with a dark shadow across it
        faint = img.point([140 + v * 100 // 255 for v in range(256)])  # lookup tables
        grad = Image.linear_gradient("L").rotate(90).resize(img.size)
        grad = grad.point([110 + v // 2 for v in range(256)])
        img = ImageChops.multiply(faint, grad)
    return img


def test_load_image_file_reads_text_with_boxes(tmp_path: Path) -> None:
    _tesseract_or_skip()
    path = tmp_path / "scan.png"
    _page_image().save(path)
    doc = load(str(path))
    assert doc.blocks[0].text == "# Harbour Report"
    assert "approved two new berths for the fishing fleet" in doc.markdown
    assert doc.quality.extraction_method == "ocr"
    assert doc.quality.ocr_confidence is not None
    assert doc.quality.ocr_confidence > 0.8
    block = doc.blocks[1]
    assert block.provenance.kind == "image"
    assert block.provenance.page == 1
    assert block.provenance.bbox is not None
    assert block.provenance.bbox[0] == pytest.approx(80, abs=15)  # pixels of the original


def test_shadowed_scan_is_still_read(tmp_path: Path) -> None:
    _tesseract_or_skip()
    path = tmp_path / "shadow.jpg"
    _page_image(shadow=True).convert("RGB").save(path, quality=60)
    doc = load(str(path))
    assert "fishing fleet" in doc.markdown


def test_scanned_pdf_page_is_ocred(tmp_path: Path) -> None:
    _tesseract_or_skip()
    img = Image.new("RGB", (1275, 1650), "white")  # a Letter page scanned at 150 dpi
    img.paste(_page_image().resize((1200, 525)).convert("RGB"), (40, 60))
    text_page = Page(flow([("Cover page with a real text layer for the report.", 11, False)]))
    scan = Page(image=(img.width, img.height, img.tobytes()))
    path = tmp_path / "mixed.pdf"
    path.write_bytes(build_pdf([text_page, scan]))
    doc = load(str(path))
    assert "Cover page with a real text layer" in doc.markdown
    assert "fishing fleet" in doc.markdown
    kinds = {b.provenance.page: b.provenance.kind for b in doc.blocks}
    assert kinds == {1: "pdf", 2: "image"}
    assert any(s.rung == "ocr" and s.ok for s in doc.fetch_trace.steps)
    assert doc.quality.ocr_confidence is not None
    ocr_block = next(b for b in doc.blocks if b.provenance.page == 2)
    assert ocr_block.provenance.bbox is not None
    assert ocr_block.provenance.bbox[2] <= 612  # converted back to PDF points


def test_ocr_never_reports_scanned_pages(tmp_path: Path) -> None:
    scan = Page(image=(4, 4, bytes([255]) * 48))
    text_page = Page(flow([("A page with a real text layer and enough words.", 11, False)]))
    path = tmp_path / "mixed.pdf"
    path.write_bytes(build_pdf([text_page, scan]))
    doc = load(str(path), ocr="never")
    assert any("OCR was not available: ocr='never'" in w for w in doc.quality.warnings)


def test_corrupt_image_is_a_clear_error(tmp_path: Path) -> None:
    _tesseract_or_skip()
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    with pytest.raises(UnsupportedSourceError, match="Could not open the image"):
        load(str(path))


# ------------------------------------------------- PDF text layer vs OCR cross-check
REPORT = [
    ("Harbour Report", 20, True),
    (
        "The harbour board met eleven times this year and approved two new berths for the "
        "fishing fleet, which had been waiting since the storm of last winter. Income rose by "
        "four per cent, mostly from mooring fees and the new fuel station on the east pier.",
        11,
        False,
    ),
]


def test_broken_text_layer_is_replaced_by_ocr(tmp_path: Path) -> None:
    _tesseract_or_skip()
    path = tmp_path / "broken.pdf"
    path.write_bytes(build_pdf([Page(flow(REPORT))], broken_unicode=True))  # "Uif ibscpvs"
    doc = load(str(path))
    assert "harbour board met eleven times" in doc.markdown
    assert "ibscpvs" not in doc.markdown
    assert {b.provenance.kind for b in doc.blocks} == {"image"}
    assert any("text layer does not match" in w for w in doc.quality.warnings)
    step = next(s for s in doc.fetch_trace.steps if s.rung == "text-check")
    assert "suspicious text" in (step.detail or "")
    assert "used OCR" in (step.detail or "")


def test_good_text_layer_is_confirmed(tmp_path: Path) -> None:
    _tesseract_or_skip()
    path = tmp_path / "good.pdf"
    path.write_bytes(build_pdf([Page(flow(REPORT))]))
    doc = load(str(path))
    assert {b.provenance.kind for b in doc.blocks} == {"pdf"}  # the layer is kept
    conf = doc.quality.extraction_confidence
    assert conf is not None
    assert conf > 0.85  # sampled page agrees with OCR
    assert not any("does not match" in w for w in doc.quality.warnings)


def test_bad_hidden_ocr_layer_on_a_scan_is_replaced(tmp_path: Path) -> None:
    _tesseract_or_skip()
    img = Image.new("RGB", (1275, 1650), "white")  # the visible scan
    img.paste(_page_image().resize((1200, 525)).convert("RGB"), (40, 60))
    hidden = [  # an old, poor OCR layer: plausible-looking but wrong words
        Line("Hanbor Repont", 72, 700, 11, invisible=True),
        Line("Tlie bnard rnet elcvcn tirnes tliis yeur arid approvcd", 72, 680, 11, invisible=True),
        Line("lwo ncw bcrtlis for tlic flshing flcct in tlie nortli", 72, 666, 11, invisible=True),
    ]
    path = tmp_path / "scan_with_bad_ocr.pdf"
    path.write_bytes(build_pdf([Page(hidden, image=(img.width, img.height, img.tobytes()))]))
    doc = load(str(path))
    assert "approved two new berths" in doc.markdown
    assert "rnet" not in doc.markdown
    assert any("text layer does not match" in w for w in doc.quality.warnings)


# ------------------------------------------------------------------ glyphly engine
def _fake_glyphly(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """A stand-in for the glyphly package: two body lines and a taller title line."""
    import sys
    import types
    from dataclasses import dataclass, field

    @dataclass
    class W:
        text: str
        box: tuple[float, float, float, float]
        confidence: float

    @dataclass
    class L:
        words: list[W]
        box: tuple[float, float, float, float]

    @dataclass
    class P:
        lines: list[L]
        width: int = 400
        height: int = 300
        steps: list[str] = field(default_factory=lambda: ["3 text lines found"])

    calls: list[object] = []

    class Reader:
        def read(self, image: object) -> P:
            calls.append(image)
            return P([
                L([W("Report", (10, 10, 120, 50), 0.99)], (10, 10, 120, 50)),
                L([W("hello", (10, 70, 60, 90), 0.98), W("world", (70, 70, 130, 90), 0.97)],
                  (10, 70, 130, 90)),
                L([W("again", (10, 100, 60, 122), 0.96)], (10, 100, 60, 122)),
            ])  # fmt: skip

    module = types.ModuleType("glyphly")
    module.Reader = Reader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "glyphly", module)
    from gleanly.ocr import glyph

    monkeypatch.setattr(glyph, "_reader", None)
    return calls


def test_glyphly_adapter_words_lines_and_sizes(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_glyphly(monkeypatch)
    from gleanly.ocr import glyph

    res = glyph.ocr_image(Image.new("RGB", (400, 300), "white"), scale=0.5)
    assert [w.text for w in res.words] == ["Report", "hello", "world", "again"]
    assert [w.line_end for w in res.words] == [True, False, True, True]
    assert res.words[1].x0 == 5.0  # pixels scaled to output units
    assert res.width == 200.0
    # body lines (20 and 22 px) share one size; the 40 px title keeps its own
    assert res.words[1].size == res.words[3].size == 11.0
    assert res.words[0].size == 20.0
    assert res.steps[0] == "glyphly"
    assert res.confidence is not None


def test_auto_prefers_glyphly_and_tesseract_stays_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _fake_glyphly(monkeypatch)
    path = tmp_path / "scan.png"
    Image.new("RGB", (400, 300), "white").save(path)
    doc = load(str(path))  # ocr_engine="auto"
    assert calls  # glyphly did the reading
    assert "hello world" in doc.markdown
    assert doc.blocks[0].provenance.kind == "image"


def test_glyphly_requested_but_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "glyphly", None)  # import fails
    path = tmp_path / "scan.png"
    Image.new("RGB", (40, 30), "white").save(path)
    with pytest.raises(UnsupportedSourceError, match="pip install glyphly"):
        load(str(path), ocr_engine="glyphly")
