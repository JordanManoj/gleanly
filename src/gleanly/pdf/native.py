"""Native PDFs: read the text layer with page + bounding-box provenance.

Uses pypdfium2 (PDFium, the PDF engine in Chrome; BSD-3/Apache-2.0), installed with
``pip install gleanly[pdf]``. Pages without a text layer (scans) are reported so the OCR
rung can handle them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from gleanly.clean.html import Extraction, RawBlock
from gleanly.errors import UnsupportedSourceError
from gleanly.pdf.layout import PageText, Word, layout

# A page with fewer visible characters than this has no usable text layer (likely a scan).
MIN_PAGE_CHARS = 20
_PDF_DATE = re.compile(r"D:(\d{4})(\d{2})?(\d{2})?")


@dataclass
class PdfText:
    extraction: Extraction
    page_count: int
    pages: list[PageText]
    empty_pages: list[int] = field(default_factory=list)  # 1-based pages with no text layer
    info: dict[str, str] = field(default_factory=dict)
    ocr_pages: list[int] = field(default_factory=list)  # empty pages that OCR filled in
    ocr_confidence: float | None = None
    ocr_steps: list[str] = field(default_factory=list)


class OcrConfidence:
    @staticmethod
    def of(words: list[Word]) -> float | None:
        """Length-weighted mean word confidence."""
        scored = [(w.conf, len(w.text)) for w in words if w.conf is not None]
        total = sum(n for _, n in scored)
        return sum(c * n for c, n in scored) / total if total else None


class _OcrOutput(Protocol):
    words: list[Word]
    steps: list[str]


# Renders a scanned page image and returns its OCR words, in PDF points (2nd argument:
# points per rendered pixel).
PageOcr = Callable[[Any, float], _OcrOutput]
OCR_DPI = 300


def _pdfium() -> Any:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise UnsupportedSourceError(
            "Reading PDFs needs the [pdf] extra: pip install 'gleanly[pdf]'"
        ) from exc
    return pdfium


_BOLD_NAME = re.compile(r"bold|black|heavy|semibold|demi", re.I)
_LINE_END_HYPHEN = "\ufffe"  # PDFium's marker for a hyphen at the end of a line


def _is_bold(raw: Any, textpage: Any, index: int, buf: Any) -> bool:
    if int(raw.FPDFText_GetFontWeight(textpage, index)) >= 600:
        return True
    # Standard fonts (Helvetica-Bold, ...) often report no weight: check the name.
    n = raw.FPDFText_GetFontInfo(textpage, index, buf, len(buf), None)
    return bool(n) and bool(_BOLD_NAME.search(buf.raw[: max(n - 1, 0)].decode("latin-1")))


def _page_words(page: Any, height: float) -> list[Word]:
    import ctypes

    import pypdfium2.raw as raw

    buf = ctypes.create_string_buffer(128)

    tp = page.get_textpage()
    try:
        n = tp.count_chars()
        words: list[Word] = []
        chars: list[tuple[str, tuple[float, float, float, float], float, bool]] = []

        def flush(line_end: bool) -> None:
            if not chars:
                return
            text = "".join(c[0] for c in chars)
            boxes = [c[1] for c in chars]
            words.append(
                Word(
                    text=text,
                    x0=min(b[0] for b in boxes),
                    top=height - max(b[3] for b in boxes),
                    x1=max(b[2] for b in boxes),
                    bottom=height - min(b[1] for b in boxes),
                    size=max(c[2] for c in chars),
                    bold=sum(c[3] for c in chars) > len(chars) / 2,
                    line_end=line_end,
                )
            )
            chars.clear()

        for i in range(n):
            ch = tp.get_text_range(i, 1)
            if ch == _LINE_END_HYPHEN:
                if chars:
                    chars.append(("-", chars[-1][1], chars[-1][2], chars[-1][3]))
                flush(True)
                continue
            if ch in ("\r", "\n"):
                if ch == "\n" or not chars:
                    flush(True)
                    if words:
                        words[-1].line_end = True
                continue
            if ch.isspace():
                flush(False)
                continue
            box = tp.get_charbox(i)
            if chars:  # a vertical jump inside a "word" is really a new line
                pb = chars[-1][1]
                line_h = max(pb[3] - pb[1], 1.0)
                if abs((box[1] + box[3]) / 2 - (pb[1] + pb[3]) / 2) > 0.8 * line_h:
                    flush(True)
            size = float(raw.FPDFText_GetFontSize(tp.raw, i))
            chars.append((ch, box, size, _is_bold(raw, tp.raw, i, buf)))
        flush(True)
        return words
    finally:
        tp.close()


def _info(pdf: Any) -> dict[str, str]:
    try:
        meta = pdf.get_metadata_dict()
    except Exception:  # broken info dictionaries are common; metadata is optional
        return {}
    return {k: str(v).strip() for k, v in meta.items() if v and str(v).strip()}


def pdf_date(value: str | None) -> str | None:
    """'D:20250314083000Z' -> '2025-03-14'."""
    m = _PDF_DATE.match(value or "")
    if not m:
        return None
    return "-".join(part for part in m.groups() if part)


def read_pdf(data: bytes, *, password: str | None = None, ocr: PageOcr | None = None) -> PdfText:
    pdfium = _pdfium()
    try:
        pdf = pdfium.PdfDocument(data, password=password)
    except pdfium.PdfiumError as exc:
        raise UnsupportedSourceError(f"Could not open the PDF: {exc}") from exc
    try:
        pages: list[PageText] = []
        empty: list[int] = []
        ocr_pages: list[int] = []
        ocr_words: list[Word] = []
        ocr_notes: list[str] = []
        for i in range(len(pdf)):
            page = pdf[i]
            kind = "pdf"
            try:
                width, height = page.get_size()
                words = _page_words(page, height)
                if sum(len(w.text) for w in words) < MIN_PAGE_CHARS:
                    empty.append(i + 1)
                    if ocr is not None:
                        image = page.render(scale=OCR_DPI / 72).to_pil()
                        result = ocr(image, 72 / OCR_DPI)
                        if result.words:
                            words, kind = result.words, "image"
                            ocr_pages.append(i + 1)
                            ocr_words += result.words
                            ocr_notes += [f"page {i + 1}: {s}" for s in result.steps]
            finally:
                page.close()
            pages.append(PageText(i + 1, width, height, words, kind=kind))
        info = _info(pdf)
    finally:
        pdf.close()
    blocks: list[RawBlock] = layout(pages, kind="pdf")
    total_chars = sum(len(w.text) + 1 for p in pages for w in p.words)
    extraction = Extraction(blocks, "pdf", page_chars=total_chars)
    ocr_conf = OcrConfidence.of(ocr_words)
    return PdfText(extraction, len(pages), pages, empty, info, ocr_pages, ocr_conf, ocr_notes)


__all__ = ["PdfText", "pdf_date", "read_pdf"]
