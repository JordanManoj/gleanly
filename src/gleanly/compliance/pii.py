"""Lightweight PII flags (v0: regex-based, tuned for precision over recall)."""

from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
_PHONE = re.compile(
    r"(?<![\w/.-])"  # not glued to a word, path or URL
    r"(?:\+\d{1,3}[\s.-]?)?"  # country code
    r"(?:\(\d{2,4}\)[\s.-]?)?"  # area code in parentheses
    r"\d{2,4}(?:[\s.-]\d{2,4}){2,4}"
    r"(?![\w/-])"
)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")
_MD_URL = re.compile(r"\]\([^)]*\)")
_DATEISH = re.compile(r"^\d{4}[-./]\d{1,2}[-./]\d{1,2}$")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def detect_pii(text: str) -> list[str]:
    """Return the sorted PII types that appear in ``text``."""
    text = _MD_URL.sub("]", text)  # link targets are not content
    found: set[str] = set()
    if _EMAIL.search(text):
        found.add("email")
    if _IBAN.search(text):
        found.add("iban")
        text = _IBAN.sub(" ", text)  # its digit groups would otherwise look like a phone
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            found.add("credit_card")
            break
    for m in _PHONE.finditer(text):
        raw = m.group().strip()
        digits = re.sub(r"\D", "", raw)
        if 9 <= len(digits) <= 15 and not _DATEISH.match(raw):
            found.add("phone")
            break
    return sorted(found)
