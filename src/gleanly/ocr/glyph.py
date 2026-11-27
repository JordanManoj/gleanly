"""OCR with glyphly: no Tesseract or other program to install.

glyphly (a separate package by the same author, Apache-2.0) runs text detection and
recognition models on ONNX Runtime and returns lines of words with boxes and
confidences. This adapter turns them into gleanly's word list, so images, scanned PDF
pages and the PDF text-layer check work exactly as with Tesseract.

Held-out results on gleanly's OCR benchmark (generated pages, character error rate):
standard suite under 0.05% (gleanly + Tesseract 0.6%), hard suite 0.1% (0.0%).
"""

from __future__ import annotations

import importlib
import statistics
from typing import TYPE_CHECKING, Any

from gleanly.ocr.engine import OcrResult
from gleanly.pdf.layout import Word

if TYPE_CHECKING:
    from PIL import Image

_readers: dict[tuple[str, ...], Any] = {}
_DOWNLOAD = True  # tests switch this off: models are never fetched during tests
# Tesseract language codes (what ``ocr_lang`` takes) -> ISO 639-1 codes glyphly takes, for
# languages glyphly reads with its own script models. Others need no hint.
_TESSERACT = {
    "mal": "ml", "ben": "bn", "asm": "as", "kan": "kn", "guj": "gu", "pan": "pa",
    "ori": "or", "hin": "hi", "mar": "mr", "nep": "ne", "san": "sa", "tam": "ta",
    "tel": "te", "ara": "ar", "fas": "fa", "urd": "ur", "rus": "ru", "ukr": "uk",
    "bel": "be", "bul": "bg", "srp": "sr", "mkd": "mk", "ell": "el", "kor": "ko",
    "tha": "th",
}  # fmt: skip
SAME_SIZE = 0.2  # line heights within 20% of the page's typical one are body text


def available() -> bool:
    """True when glyphly can be imported (the ``[ocr]`` extra installs it)."""
    try:
        importlib.import_module("glyphly")
    except ImportError:
        return False
    return True


def glyphly_langs(ocr_lang: str) -> tuple[str, ...]:
    """Language hints for glyphly from ``ocr_lang`` ('eng', 'mal', 'eng+ben', 'ml', ...).

    Only languages glyphly reads with a script model are passed on; glyphly needs to be
    told about some of them (Malayalam, Bengali, ...), and auto mode stays on for the rest.
    """
    out = []
    for code in ocr_lang.replace(",", "+").split("+"):
        code = code.strip().lower()
        iso = _TESSERACT.get(code, code if len(code) == 2 else "")
        if iso and iso != "en" and iso not in out:
            out.append(iso)
    return tuple(out)


def _get_reader(langs: tuple[str, ...] = ()) -> Any:
    if langs not in _readers:
        glyphly = importlib.import_module("glyphly")
        # loads the models once (downloads them on first use)
        lang: Any = ["auto", *langs] if langs else "auto"
        _readers[langs] = glyphly.Reader(lang=lang, download=_DOWNLOAD)
    return _readers[langs]


def ocr_image(image: Image.Image, *, scale: float = 1.0, lang: str = "eng") -> OcrResult:
    """OCR one page image with glyphly. ``scale`` converts pixels to output units;
    ``lang`` is gleanly's ``ocr_lang`` (Tesseract-style codes)."""
    page = _get_reader(glyphly_langs(lang)).read(image)
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
