"""OCR with glyphly: no Tesseract or other program to install.

glyphly (a separate package by the same author, Apache-2.0) runs text detection and
recognition models on ONNX Runtime and returns lines of words with boxes and
confidences. This adapter turns them into gleanly's word list, so images, scanned PDF
pages and the PDF text-layer check work exactly as with Tesseract.

Held-out results on gleanly's OCR benchmark (generated pages, character error rate):
standard suite under 0.05% (gleanly + Tesseract 0.6%), hard suite 0.1% (0.0%).
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING, Any

from gleanly.ocr.engine import OcrResult
from gleanly.pdf.layout import Word

if TYPE_CHECKING:
    from PIL import Image

_reader: Any = None
SAME_SIZE = 0.2  # line heights within 20% of the page's typical one are body text


def available() -> bool:
    try:
        import glyphly  # noqa: F401
    except ImportError:
        return False
    return True


def _get_reader() -> Any:
    global _reader
    if _reader is None:
        import glyphly

        _reader = glyphly.Reader()  # loads the models once (downloads them on first use)
    return _reader


def ocr_image(image: Image.Image, *, scale: float = 1.0) -> OcrResult:
    """OCR one page image with glyphly. ``scale`` converts pixels to output units."""
    page = _get_reader().read(image)
    words: list[Word] = []
    heights = [line.box[3] - line.box[1] for line in page.lines]
    body = statistics.median(heights) if heights else 0.0
    for line, raw in zip(page.lines, heights, strict=True):
        # Line boxes vary by a few pixels with the letters in them (ascenders, descenders);
        # gleanly's layout reads a size change as a new paragraph or a heading, so lines
        # within SAME_SIZE of the page's typical height count as body text.
        same = body and abs(raw - body) <= SAME_SIZE * body
        height = (body if same else raw) * scale
        for i, w in enumerate(line.words):
            x0, top, x1, bottom = w.box
            words.append(
                Word(
                    w.text,
                    x0 * scale,
                    top * scale,
                    x1 * scale,
                    bottom * scale,
                    size=round(height, 1),
                    line_end=i == len(line.words) - 1,
                    conf=float(w.confidence),
                )
            )
    steps = ["glyphly", *page.steps]
    return OcrResult(words, page.width * scale, page.height * scale, steps)


__all__ = ["available", "ocr_image"]
