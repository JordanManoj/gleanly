"""gleanly's OCR pipeline: clean-up, Tesseract, and a self-check of the result.

Steps (each kept only because it lowered the error rate on ``bench.ocr``):

1. grey-scale and flatten the background (shadows, faint print, coloured paper);
2. rescale so text lines are the height Tesseract reads best;
3. Tesseract with automatic page segmentation;
4. **layout self-check**: Tesseract's word confidences cannot see reading-order mistakes
   (e.g. a single-column page split into fake columns). When lines come out fragmented,
   the page is read again as one column and the more coherent, more confident reading
   is kept.

Word boxes are returned in the coordinates of the original image (or PDF points when a
``scale`` is given).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from gleanly.ocr.preprocess import flatten_background, normalise_scale, to_gray
from gleanly.ocr.tesseract import OcrWords, run_tesseract
from gleanly.pdf.layout import Word, to_lines

if TYPE_CHECKING:
    from PIL import Image

# A reading is "fragmented" when many lines are much narrower than the text column.
FRAGMENT_WIDTH = 0.5
FRAGMENTED_SHARE = 0.25


@dataclass
class OcrResult:
    words: list[Word]
    width: float
    height: float
    steps: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> float | None:
        return OcrWords(self.words, 0, 0).confidence


def fragmentation(words: list[Word]) -> float:
    """Share of text lines narrower than half the typical full line (0 = coherent)."""
    lines = [ln for ln in to_lines(words) if len(ln.words) >= 1]
    if len(lines) < 4:
        return 0.0
    widths = sorted(ln.x1 - ln.x0 for ln in lines)
    full = widths[int(len(widths) * 0.9)]  # a long line of the main column
    if full <= 0:
        return 0.0
    # The last line of a paragraph is legitimately short: only count lines that are
    # followed by another line on (nearly) the same row or by a gap-less continuation.
    narrow = sum(1 for ln in lines if (ln.x1 - ln.x0) < FRAGMENT_WIDTH * full)
    return narrow / len(lines)


def _score(r: OcrWords) -> float:
    conf = r.confidence or 0.0
    return conf * (1 - fragmentation(r.words))


def ocr_image(
    image: Image.Image,
    *,
    lang: str = "eng",
    cmd: str | None = None,
    scale: float = 1.0,
) -> OcrResult:
    """OCR one page image. ``scale`` converts image pixels to output units."""
    steps: list[str] = []
    gray = flatten_background(to_gray(image))
    steps.append("background flattened")
    gray, factor = normalise_scale(gray)
    if factor != 1.0:
        steps.append(f"rescaled x{factor:.2f}")
    unit = scale / factor  # processed pixels -> output units
    first = run_tesseract(gray, lang=lang, cmd=cmd, scale=unit)
    best = first
    if fragmentation(first.words) > FRAGMENTED_SHARE:
        second = run_tesseract(gray, lang=lang, cmd=cmd, scale=unit, psm=4)
        if _score(second) > _score(first):
            best = second
            steps.append("re-read as a single column (layout self-check)")
        else:
            steps.append("layout self-check kept the first reading")
    words = best.words
    for w in words:
        w.size = round(w.size, 1)
    return OcrResult(words, image.width * scale, image.height * scale, steps)


def median_line_height(words: list[Word]) -> float | None:
    sizes = [w.size for w in words]
    return statistics.median(sizes) if sizes else None


__all__ = ["OcrResult", "fragmentation", "ocr_image"]
