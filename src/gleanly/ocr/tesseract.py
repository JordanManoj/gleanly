"""Run the Tesseract program and read its per-word output.

gleanly calls the ``tesseract`` executable directly (no Python binding) and asks for TSV
output, which gives every word with its box and a confidence. The image is passed on
stdin, so no temporary files are written.

Tesseract (Apache-2.0) is installed separately: https://github.com/tesseract-ocr/tesseract
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from gleanly.errors import UnsupportedSourceError
from gleanly.pdf.layout import Word

if TYPE_CHECKING:
    from PIL import Image

# Where the official installers put tesseract when it is not on PATH.
_DEFAULT_LOCATIONS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
]
INSTALL_HINT = (
    "OCR needs the Tesseract program: install it from "
    "https://github.com/tesseract-ocr/tesseract (Windows: the UB Mannheim installer; "
    "macOS: brew install tesseract; Linux: apt install tesseract-ocr), or pass its path "
    "as tesseract_cmd."
)


@lru_cache(maxsize=8)
def find_tesseract(cmd: str | None = None) -> str:
    """The tesseract executable: ``cmd``, $TESSERACT_CMD, PATH, then the usual folders."""
    for candidate in (cmd, os.environ.get("TESSERACT_CMD"), shutil.which("tesseract")):
        if candidate and Path(candidate).is_file():
            return candidate
    for loc in _DEFAULT_LOCATIONS:
        if Path(loc).is_file():
            return loc
    raise UnsupportedSourceError(INSTALL_HINT)


@lru_cache(maxsize=8)
def available_languages(cmd: str) -> frozenset[str]:
    out = subprocess.run(
        [cmd, "--list-langs"], capture_output=True, text=True, timeout=60, check=False
    )
    langs = out.stdout.splitlines()[1:]  # first line is a header
    return frozenset(lang.strip() for lang in langs if lang.strip())


@dataclass
class OcrWords:
    words: list[Word]
    width: int
    height: int

    @property
    def confidence(self) -> float | None:
        """Mean word confidence (0-1), weighted by word length."""
        scored = [(w.conf, len(w.text)) for w in self.words if w.conf is not None]
        total = sum(n for _, n in scored)
        return sum(c * n for c, n in scored) / total if total else None


def parse_tsv(tsv: str, *, scale: float = 1.0) -> list[Word]:
    """Tesseract TSV -> words in reading order, with line ends and line heights.

    ``scale`` converts pixel coordinates back to the caller's units (e.g. PDF points).
    """
    rows = [line.split("\t") for line in tsv.splitlines()[1:]]
    line_height: dict[tuple[str, str, str, str], float] = {}
    words: list[tuple[tuple[str, str, str, str], Word]] = []
    for r in rows:
        if len(r) < 12:
            continue
        level = r[0]
        key = (r[1], r[2], r[3], r[4])  # page, block, paragraph, line
        left, top, width, height = (int(v) for v in r[6:10])
        if level == "4":
            line_height[key] = height * scale
        elif level == "5":
            text = r[11].strip()
            conf = float(r[10])
            if not text or conf < 0:
                continue
            words.append(
                (
                    key,
                    Word(
                        text=text,
                        x0=left * scale,
                        top=top * scale,
                        x1=(left + width) * scale,
                        bottom=(top + height) * scale,
                        size=0.0,
                        conf=conf / 100,
                    ),
                )
            )
    out: list[Word] = []
    for i, (key, w) in enumerate(words):
        w.size = line_height.get(key, w.bottom - w.top)
        w.line_end = i + 1 == len(words) or words[i + 1][0] != key
        out.append(w)
    return out


def run_tesseract(
    image: Image.Image,
    *,
    lang: str = "eng",
    psm: int = 3,
    cmd: str | None = None,
    scale: float = 1.0,
    timeout: float = 120,
) -> OcrWords:
    """OCR one image. ``psm`` is Tesseract's page segmentation mode (3 = automatic)."""
    exe = find_tesseract(cmd)
    missing = [part for part in lang.split("+") if part not in available_languages(exe)]
    if missing:
        raise UnsupportedSourceError(
            f"Tesseract has no language data for {', '.join(missing)}. Install the "
            f"traineddata file(s) or pass a different lang."
        )
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}  # one process per page scales better
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            [exe, "stdin", "stdout", "-l", lang, "--psm", str(psm), "tsv"],
            input=buf.getvalue(),
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired as exc:
        raise UnsupportedSourceError(f"Tesseract timed out after {timeout}s.") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise UnsupportedSourceError(f"Tesseract failed: {err[:300]}")
    tsv = proc.stdout.decode("utf-8", errors="replace")
    return OcrWords(parse_tsv(tsv, scale=scale), image.width, image.height)


__all__ = ["INSTALL_HINT", "OcrWords", "find_tesseract", "parse_tsv", "run_tesseract"]
