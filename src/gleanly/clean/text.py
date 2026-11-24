"""Words and tokens in any language.

Thresholds across gleanly (how much text counts as "poor", "prose", a repeat) were tuned
in words. Splitting on spaces only works for languages that put spaces between words:
Chinese and Japanese do not, nor do Thai, Lao, Khmer and Burmese. So:

- each Chinese or Japanese character counts as one word (the usual convention, e.g. in
  word processors);
- Thai, Lao, Khmer and Burmese characters count as a quarter of a word each (words there
  average about four characters);
- everything else is counted by spaces, exactly as before, so English and other
  space-separated languages get the same numbers as before.

``tokens`` splits text into comparable units for the extraction cross-check: words for
spaced scripts, single characters for unspaced ones (a whole Chinese sentence would
otherwise be one "word" that only matches if both sides cut it identically).
"""

from __future__ import annotations

import re

_CJK = (
    "぀-ヿ"  # Hiragana, Katakana
    "ㇰ-ㇿ"  # Katakana extensions
    "㐀-䶿"  # Han extension A
    "一-鿿"  # Han
    "豈-﫿"  # Han compatibility
    "ｦ-ﾟ"  # half-width Katakana
    "\U00020000-\U0002ffff"  # Han extensions B-F
)
_SEA = (
    "฀-๿"  # Thai
    "຀-໿"  # Lao
    "က-႟"  # Myanmar
    "ក-៿"  # Khmer
)
_CJK_RE = re.compile(f"[{_CJK}]")
_SEA_RE = re.compile(f"[{_SEA}]")
# Combining marks (accents, Indic vowel signs, Arabic and Hebrew points) belong to their
# word; Python's \\w does not include them, which would cut Hindi words apart.
_MARKS = (
    "\u0300-\u036f\u0483-\u0489\u0591-\u05c7\u0610-\u061a\u064b-\u065f\u0670"
    "\u06d6-\u06ed\u0900-\u0963\u0966-\u0dff\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f"
)
_TOKEN = re.compile(f"[{_CJK}]|[{_SEA}]|(?:(?![{_CJK}{_SEA}])[\\w{_MARKS}])+")
SEA_CHARS_PER_WORD = 4


def count_words(text: str) -> int:
    """Number of words, counting unspaced scripts by characters."""
    total = 0.0
    for tok in text.split():
        cjk = len(_CJK_RE.findall(tok))
        sea = len(_SEA_RE.findall(tok))
        if not cjk and not sea:
            total += 1
            continue
        total += cjk + sea / SEA_CHARS_PER_WORD
        rest = _SEA_RE.sub("", _CJK_RE.sub("", tok))
        if any(ch.isalnum() for ch in rest):
            total += 1  # a Latin word or a number glued to the characters
    return round(total)


def tokens(text: str) -> list[str]:
    """Lower-cased comparison units: words, or single characters in unspaced scripts."""
    return [t.lower() for t in _TOKEN.findall(text)]


__all__ = ["count_words", "tokens"]
