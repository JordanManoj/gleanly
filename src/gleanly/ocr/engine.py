"""gleanly's OCR pipeline: image clean-up, then Tesseract.

Steps, each kept only because it lowered the character error rate on ``bench.ocr``
(dev split; see bench/README.md for the numbers and for what was tried and dropped):

1. grey-scale and flatten the background (shadows, faint print, coloured paper):
   mean CER 16.6% -> 2.3%;
2. rescale so text lines are about 26 px high (measured in narrow strips, so skewed
   pages are measured correctly): 2.3% -> 1.4%;
3. Tesseract with automatic page segmentation.

Word boxes are returned in the coordinates of the original image, or in other units
(e.g. PDF points) when a ``scale`` is given.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from gleanly.ocr.preprocess import flatten_background, normalise_scale, to_gray
from gleanly.ocr.tesseract import OcrWords, run_tesseract
from gleanly.pdf.layout import Word

if TYPE_CHECKING:
    from PIL import Image


@dataclass
class OcrResult:
    words: list[Word]
    width: float
    height: float
    steps: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> float | None:
        return OcrWords(self.words, 0, 0).confidence


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
    result = run_tesseract(gray, lang=lang, cmd=cmd, scale=scale / factor)
    for w in result.words:
        w.size = round(w.size, 1)
    return OcrResult(result.words, image.width * scale, image.height * scale, steps)


__all__ = ["OcrResult", "ocr_image"]
