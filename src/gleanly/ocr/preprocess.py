"""Image clean-up before OCR, using Pillow only.

- **Flatten the background**: estimate the paper (a max filter removes the dark text, a
  blur smooths it) and subtract the page from it, so shadows, gradients and grey paper
  become white while ink keeps its darkness; then stretch the contrast.
- **Normalise the text size**: measure the typical text-line height from the row ink
  profile and rescale so lines are the height Tesseract reads best. Large scans also get
  faster this way.
"""

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

# Text-line height (pixels, as measured by line_height) that Tesseract reads best.
TARGET_LINE_PX = 26  # chosen on bench.ocr dev: 18, 22, 32 were worse
# Only shrink: enlarging broke ruled tables and cost accuracy on fax-quality pages
# (bench.ocr dev, both suites: mean CER 3.0% -> 1.3%). Open item: clean 300 dpi Courier
# pages read worse unscaled (1.8% -> 7.5%).
MIN_SCALE, MAX_SCALE = 0.25, 1.0


def to_gray(img: Image.Image) -> Image.Image:
    from PIL import Image as PILImage

    if img.mode in ("RGBA", "LA", "P"):
        background = PILImage.new("RGBA", img.size, (255, 255, 255, 255))
        img = PILImage.alpha_composite(background, img.convert("RGBA"))
    gray = img.convert("L")
    if _mean(gray) < DARK_PAGE:  # light text on a dark page: make it dark on light
        from PIL import ImageOps

        gray = ImageOps.invert(gray)
    return gray


DARK_PAGE = 100  # mean brightness below this = light text on a dark background


def _mean(gray: Image.Image) -> float:
    small = gray.resize((max(1, gray.width // 8), max(1, gray.height // 8)))
    data = small.tobytes()
    return sum(data) / len(data) if data else 255.0


def flatten_background(gray: Image.Image) -> Image.Image:
    """Remove uneven lighting and paper colour; keep ink darkness."""
    from PIL import ImageChops, ImageFilter, ImageOps

    small = gray.reduce(4) if min(gray.size) >= 400 else gray
    bg = small.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(6))
    bg = bg.resize(gray.size)
    ink = ImageChops.subtract(bg, gray)  # 0 on paper, > 0 where there is ink
    flat = ImageChops.invert(ink)
    return ImageOps.autocontrast(flat, cutoff=(1, 0))


STRIPS = 6  # narrow vertical strips used to measure line height


SOLID_ROW = 0.25  # a row this dark across a whole strip is a ruling line, not text
MIN_RUN = 4  # shorter runs are noise or thin rules


def _runs(column: list[int]) -> list[int]:
    """Lengths of runs of rows that contain ink in one strip's row profile.

    Solid rows (table rules, underlines, borders) end a run instead of extending it:
    otherwise a ruled table looks like 3 px "text" and gets blown up far too much.
    """
    paper = statistics.median(column) if column else 255
    solid = paper * SOLID_ROW
    runs, n = [], 0
    for v in column:
        if solid < v < paper - 4:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    return [r for r in runs if r >= MIN_RUN]


def line_height(gray: Image.Image) -> float | None:
    """Typical text-line height: median height of inked row runs in narrow strips.

    Measured in several narrow vertical strips rather than across the full width: on a
    tilted page, a line spans many rows over the full width and neighbouring lines merge,
    but over a narrow strip a few degrees of skew barely move it.
    """
    strip_w = max(8, min(gray.width // (2 * STRIPS), 160))
    runs: list[int] = []
    for i in range(STRIPS):
        x0 = round((i + 0.5) * gray.width / STRIPS - strip_w / 2)
        strip = gray.crop((x0, 0, x0 + strip_w, gray.height))
        runs += _runs(list(strip.resize((1, gray.height)).tobytes()))  # mean per row
    return float(statistics.median(runs)) if runs else None


def normalise_scale(gray: Image.Image) -> tuple[Image.Image, float]:
    """Rescale so text lines are about TARGET_LINE_PX high. Returns (image, factor)."""
    from PIL import Image as PILImage

    h = line_height(gray)
    if not h:
        return gray, 1.0
    factor = max(MIN_SCALE, min(MAX_SCALE, TARGET_LINE_PX / h))
    if 0.85 <= factor <= 1.15:
        return gray, 1.0
    size = (max(1, round(gray.width * factor)), max(1, round(gray.height * factor)))
    return gray.resize(size, PILImage.Resampling.LANCZOS), factor


__all__ = ["flatten_background", "line_height", "normalise_scale", "to_gray"]
