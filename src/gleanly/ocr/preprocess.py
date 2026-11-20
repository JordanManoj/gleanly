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

# Text-line height (pixels, ascender to descender) that Tesseract reads most reliably.
TARGET_LINE_PX = 32
MIN_SCALE, MAX_SCALE = 0.25, 3.0


def to_gray(img: Image.Image) -> Image.Image:
    from PIL import Image as PILImage

    if img.mode in ("RGBA", "LA", "P"):
        background = PILImage.new("RGBA", img.size, (255, 255, 255, 255))
        img = PILImage.alpha_composite(background, img.convert("RGBA"))
    return img.convert("L")


def flatten_background(gray: Image.Image) -> Image.Image:
    """Remove uneven lighting and paper colour; keep ink darkness."""
    from PIL import ImageChops, ImageFilter, ImageOps

    small = gray.reduce(4) if min(gray.size) >= 400 else gray
    bg = small.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(6))
    bg = bg.resize(gray.size)
    ink = ImageChops.subtract(bg, gray)  # 0 on paper, > 0 where there is ink
    flat = ImageChops.invert(ink)
    return ImageOps.autocontrast(flat, cutoff=(1, 0))


def line_height(gray: Image.Image) -> float | None:
    """Median height of runs of rows that contain ink (one run ~ one text line)."""
    width = min(gray.width, 1200)
    small = gray.resize((width, gray.height))
    rows = list(small.resize((1, gray.height)).tobytes())  # mean brightness per row
    paper = statistics.median(rows) if rows else 255
    inked = [v < paper - 4 for v in rows]
    runs, n = [], 0
    for flag in inked:
        if flag:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    runs = [r for r in runs if r >= 3]
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
