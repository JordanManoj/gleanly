"""Words with boxes -> lines -> paragraphs, headings and lists.

Shared by the native PDF reader and OCR: both produce positioned words, and both need the
same reading structure. Coordinates are points (PDF) or pixels (images) with the origin
at the top-left of the page; ``top < bottom``.

Method (established, plus two additions):

- Words become lines when the source says a line ended or the baseline jumps.
- Lines become paragraphs at vertical gaps larger than the usual line pitch, at font-size
  or style changes, and at list bullets. Hyphenated line breaks are re-joined.
- Headings: short paragraphs set larger than the body text (the most common size by
  character count), ranked by size; short bold lines become the lowest heading level.
- **Running headers and footers** are learned across pages: lines in the top or bottom
  margin that repeat (digits ignored) on at least half the pages are dropped, as are bare
  page numbers. This is gleanly's cross-page template idea, applied to documents.
"""

from __future__ import annotations

import itertools
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from gleanly.clean.html import RawBlock
from gleanly.models import BlockType

# Bullets: common bullet glyphs, dashes, U+FFFD (a symbol-font bullet with no Unicode
# mapping), "1." / "1)" / "a)" numbering.
_BULLET_CHARS = "\u2022\u25e6\u25aa\u25ab\u2023\u2219\u00b7\u25cf\u25cb\u25a0\u25a1*\ufffd"
_DASHES = "\\-\u2013\u2014"
BULLET = re.compile(rf"^(?:[{_BULLET_CHARS}{_DASHES}]|\(?\d{{1,2}}[.)]|\(?[a-z][.)])\s+")
PAGE_NUMBER = re.compile(
    rf"^(?:page\s*)?[{_DASHES}]?\s*\d{{1,4}}\s*[{_DASHES}]?(?:\s*(?:of|/)\s*\d{{1,4}})?$", re.I
)
MARGIN = 0.08  # top/bottom share of the page where running headers and footers live
HEADING_RATIO = 1.15  # a heading is set at least this much larger than the body text
HEADING_MAX_WORDS = 20
BOLD_HEADING_MAX_WORDS = 8


@dataclass
class Word:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size: float  # font size (PDF) or line height (OCR)
    bold: bool = False
    line_end: bool = False  # the source marked the end of a line after this word
    conf: float | None = None  # OCR confidence 0-1


@dataclass
class TextLine:
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def size(self) -> float:
        return statistics.median(w.size for w in self.words)

    @property
    def bold(self) -> bool:
        return sum(len(w.text) for w in self.words if w.bold) > 0.6 * len(self.text)


@dataclass
class PageText:
    number: int  # 1-based
    width: float
    height: float
    words: list[Word] = field(default_factory=list)
    kind: str | None = None  # provenance kind for this page; "image" = text read by OCR


def to_lines(words: list[Word]) -> list[TextLine]:
    lines: list[TextLine] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            prev = cur[-1]
            height = max(prev.bottom - prev.top, 1.0)
            jump = abs((w.top + w.bottom) / 2 - (prev.top + prev.bottom) / 2) > 0.6 * height
            if prev.line_end or jump:
                lines.append(TextLine(cur))
                cur = []
        cur.append(w)
    if cur:
        lines.append(TextLine(cur))
    return lines


def _norm_furniture(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())


def drop_running_lines(pages: list[list[TextLine]], heights: list[float]) -> list[list[TextLine]]:
    """Remove running headers/footers (repeated margin lines) and bare page numbers."""
    in_margin: list[list[bool]] = []
    counts: Counter[str] = Counter()
    for lines, h in zip(pages, heights, strict=True):
        flags = [ln.bottom < h * MARGIN or ln.top > h * (1 - MARGIN) for ln in lines]
        in_margin.append(flags)
        counts.update({_norm_furniture(ln.text) for ln, m in zip(lines, flags, strict=True) if m})
    need = max(2, (len(pages) + 1) // 2)
    out: list[list[TextLine]] = []
    for lines, flags in zip(pages, in_margin, strict=True):
        kept = []
        for ln, margin in zip(lines, flags, strict=True):
            if margin and (
                PAGE_NUMBER.match(ln.text.strip())
                or (len(pages) >= 2 and counts[_norm_furniture(ln.text)] >= need)
            ):
                continue
            kept.append(ln)
        out.append(kept)
    return out


def body_size(pages: list[list[TextLine]]) -> float:
    sizes: Counter[float] = Counter()
    for lines in pages:
        for ln in lines:
            sizes[round(ln.size, 1)] += len(ln.text)
    return sizes.most_common(1)[0][0] if sizes else 0.0


def _join(lines: list[TextLine]) -> str:
    text = ""
    for ln in lines:
        t = ln.text.strip()
        if not text:
            text = t
        elif text.endswith("-") and len(text) > 1 and text[-2].isalpha() and t[:1].islower():
            text = text[:-1] + t  # re-join a word hyphenated at the line break
        else:
            text = f"{text} {t}"
    return text


@dataclass
class _Para:
    lines: list[TextLine]
    bullet: bool = False

    @property
    def text(self) -> str:
        return _join(self.lines)

    @property
    def size(self) -> float:
        return statistics.median(ln.size for ln in self.lines)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (
            min(ln.x0 for ln in self.lines),
            min(ln.top for ln in self.lines),
            max(ln.x1 for ln in self.lines),
            max(ln.bottom for ln in self.lines),
        )


def to_paragraphs(lines: list[TextLine]) -> list[_Para]:
    if not lines:
        return []
    pitches = [
        b.top - a.top
        for a, b in itertools.pairwise(lines)
        if 0 < b.top - a.top < 3 * max(a.size, 1) and abs(a.size - b.size) < 0.5
    ]
    # The usual line pitch inside a paragraph: a low quantile, because single-line
    # paragraphs add many larger gaps between paragraphs.
    pitch = sorted(pitches)[len(pitches) // 4] if pitches else lines[0].size * 1.3
    paras: list[_Para] = []
    for ln in lines:
        bullet = bool(BULLET.match(ln.text))
        if paras:
            prev = paras[-1].lines[-1]
            gap = ln.top - prev.top
            same_style = abs(ln.size - prev.size) < 0.5 and ln.bold == prev.bold
            if same_style and not bullet and 0 < gap <= pitch * 1.25:
                paras[-1].lines.append(ln)
                continue
        paras.append(_Para([ln], bullet))
    return paras


def to_blocks(paragraphs: list[_Para], page: int, body: float, kind: str) -> list[RawBlock]:
    """Turn paragraphs into blocks. Heading levels are filled in by :func:`rank_headings`."""
    blocks: list[RawBlock] = []
    pending_list: list[_Para] = []

    def flush_list() -> None:
        if pending_list:
            items = [BULLET.sub("", p.text, count=1) for p in pending_list]
            text = "\n".join(f"- {it}" for it in items)
            boxes = [p.bbox for p in pending_list]
            bbox = (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
            blocks.append(RawBlock(BlockType.LIST, text, None, kind=kind, page=page, bbox=bbox))
            pending_list.clear()

    for p in paragraphs:
        text = p.text
        if not text:
            continue
        if p.bullet:
            pending_list.append(p)
            continue
        flush_list()
        words = len(text.split())
        bigger = body > 0 and p.size >= body * HEADING_RATIO
        bold_title = (
            all(ln.bold for ln in p.lines)
            and len(p.lines) == 1
            and words <= BOLD_HEADING_MAX_WORDS
            and not text.endswith((".", ":", ";", ","))
        )
        if (bigger and words <= HEADING_MAX_WORDS and len(p.lines) <= 3) or bold_title:
            blocks.append(
                RawBlock(
                    BlockType.HEADING,
                    text,  # "#" marks are added once all heading sizes are known
                    None,
                    level=0,
                    kind=kind,
                    page=page,
                    bbox=p.bbox,
                    size=p.size,
                )
            )
        else:
            blocks.append(
                RawBlock(BlockType.PARAGRAPH, text, None, kind=kind, page=page, bbox=p.bbox)
            )
    flush_list()
    return blocks


def rank_headings(blocks: list[RawBlock]) -> None:
    """Largest heading size -> level 1, next -> 2, ... (at most 6); then add "#" marks."""
    sizes = sorted(
        {round(b.size or 0, 1) for b in blocks if b.type == BlockType.HEADING}, reverse=True
    )
    rank = {s: min(i + 1, 6) for i, s in enumerate(sizes)}
    for b in blocks:
        if b.type == BlockType.HEADING:
            b.level = rank[round(b.size or 0, 1)]
            b.text = f"{'#' * b.level} {b.text}"


def layout(pages: list[PageText], kind: str) -> list[RawBlock]:
    """Full pipeline for a document: words on every page -> blocks in reading order."""
    lines = [to_lines(p.words) for p in pages]
    lines = drop_running_lines(lines, [p.height for p in pages])
    # Body size per source: PDF text reports font size, OCR reports line height.
    kinds = {p.kind or kind for p in pages}
    body = {
        k: body_size([ln for p, ln in zip(pages, lines, strict=True) if (p.kind or kind) == k])
        for k in kinds
    }
    blocks: list[RawBlock] = []
    for p, page_lines in zip(pages, lines, strict=True):
        k = p.kind or kind
        blocks += to_blocks(to_paragraphs(page_lines), p.number, body[k], k)
    rank_headings(blocks)
    return blocks


__all__ = ["PageText", "TextLine", "Word", "layout", "to_lines"]
