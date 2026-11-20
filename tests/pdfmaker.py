"""A tiny PDF writer for tests: our own text, at exact positions and sizes.

Only what the tests need: Letter-size pages, the standard Helvetica fonts (no embedding),
text lines placed with absolute coordinates, and optional image-only pages.
Coordinates are PDF points with the origin at the bottom-left, as in PDF itself.
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field

PAGE_W, PAGE_H = 612, 792


@dataclass
class Line:
    text: str
    x: float
    y: float  # baseline, from the bottom of the page
    size: float = 11
    bold: bool = False
    invisible: bool = False  # text render mode 3, like the hidden OCR layer of a scan


@dataclass
class Page:
    lines: list[Line] = field(default_factory=list)
    # Optional raw RGB image covering the page (a "scanned" page): (width, height, bytes).
    image: tuple[int, int, bytes] | None = None


def _escape(text: str) -> bytes:
    raw = text.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _shifted_cmap() -> bytes:
    """A ToUnicode map that reports every printable character as the next one ("Uif")."""
    body = (
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        b"/CMapName /Shifted def /CMapType 2 def\n"
        b"1 begincodespacerange <00> <FF> endcodespacerange\n"
        b"1 beginbfrange <21> <7D> <0022> endbfrange\n"
        b"endcmap CMapName currentdict /CMap defineresource pop end end"
    )
    return b"<< /Length %d >>\nstream\n%s\nendstream" % (len(body), body)


def build_pdf(
    pages: list[Page],
    *,
    title: str | None = None,
    author: str | None = None,
    broken_unicode: bool = False,
) -> bytes:
    """``broken_unicode``: the regular font extracts as shifted gibberish but looks right."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    to_unicode = b""
    if broken_unicode:
        to_unicode = b" /ToUnicode %d 0 R" % add(_shifted_cmap())
    font = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding%s >>"
        % to_unicode
    )
    bold = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    pages_id = len(objs) + 1  # reserved below
    objs.append(b"")
    kids: list[int] = []
    for page in pages:
        ops: list[bytes] = []
        xobjects = b""
        if page.image is not None:
            w, h, data = page.image
            img = add(
                b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB "
                b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n"
                % (w, h, len(zlib.compress(data)))
                + zlib.compress(data)
                + b"\nendstream"
            )
            xobjects = b" /XObject << /Im1 %d 0 R >>" % img
            ops.append(b"q %d 0 0 %d 0 0 cm /Im1 Do Q" % (PAGE_W, PAGE_H))
        for ln in page.lines:
            f = b"/F2" if ln.bold else b"/F1"
            mode = b"3 Tr " if ln.invisible else b""
            ops.append(
                b"BT %s%s %.1f Tf %.1f %.1f Td (%s) Tj ET"
                % (mode, f, ln.size, ln.x, ln.y, _escape(ln.text))
            )
        stream = b"\n".join(ops)
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        kids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >>%s >> >>"
                % (pages_id, PAGE_W, PAGE_H, content, font, bold, xobjects)
            )
        )
    objs[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    info_parts = []
    if title:
        info_parts.append(b"/Title (%s)" % _escape(title))
    if author:
        info_parts.append(b"/Author (%s)" % _escape(author))
    info = add(b"<< %s >>" % b" ".join(info_parts)) if info_parts else None

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    trailer = b"<< /Size %d /Root %d 0 R" % (len(objs) + 1, catalog)
    if info:
        trailer += b" /Info %d 0 R" % info
    out += b"trailer\n%s >>\nstartxref\n%d\n%%%%EOF\n" % (trailer, xref)
    return bytes(out)


def flow(
    paragraphs: Sequence[tuple[str, float, bool]],
    *,
    top: float = 720,
    left: float = 72,
    width_chars: int = 85,
    leading: float = 1.35,
    para_gap: float = 10,
) -> list[Line]:
    """Lay out (text, size, bold) paragraphs as wrapped lines, top to bottom."""
    lines: list[Line] = []
    y = top
    for text, size, is_bold in paragraphs:
        words, cur = text.split(), ""
        wrap = int(width_chars * 11 / size)
        rows: list[str] = []
        for w in words:
            if cur and len(cur) + 1 + len(w) > wrap:
                rows.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            rows.append(cur)
        for row in rows:
            lines.append(Line(row, left, y, size, is_bold))
            y -= size * leading
        y -= para_gap
    return lines
