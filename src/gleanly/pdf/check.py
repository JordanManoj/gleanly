"""Check a PDF's text layer against OCR of the rendered page.

A PDF's text layer can disagree with what the page shows: fonts without a correct
character map extract as gibberish, and old scanned PDFs often carry poor invisible OCR.
Extraction tools return that text silently. gleanly compares the two readings:

- **support**: share of the text layer's words that OCR also read on the page;
- **coverage**: share of OCR's words that the text layer contains;
- **agreement** = support x sqrt(coverage), the same form as the HTML cross-check.

Pages are checked when their text looks implausible (few word-like tokens, replacement
or private-use characters) and on a small sample of other pages, so every PDF gets a
measured confidence. When the layer clearly disagrees with a confident OCR reading, the
OCR text is used for that page.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from gleanly.pdf.layout import Word

_TOKEN = re.compile(r"\w+", re.UNICODE)
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")
_VOWEL = re.compile(r"[aeiouyAEIOUYÀ-ÆÈ-ÏÒ-ÖÙ-Üà-æè-ïò-öù-ü]")
_CONSONANT_RUN = re.compile(r"[b-df-hj-np-tv-xzB-DF-HJ-NP-TV-XZ]{5,}")

# Very common short words of major Latin-script languages (en, fr, de, es, it, pt, nl).
# Real running text is full of them; text from a font with a shifted character map
# ("Uif" for "The") almost never contains them.
_FUNCTION_WORDS_TEXT = (
    "the and of to in is a for on that with as at by it be are was this from or an "
    "de la le les et des du en un une est pour que qui dans par sur au "
    "der die das und ist von zu den mit nicht ein eine im auf dem des "
    "el los las y del se por con para una es al lo "
    "il di che e per non sono della da gli "
    "o os as do da em um uma para com "
    "het een van en is op te dat zijn"
)
FUNCTION_WORDS = frozenset(_FUNCTION_WORDS_TEXT.split())
FUNCTION_MIN = 0.04  # share of tokens that are function words, for pages of 30+ tokens
WORDLIKE_MIN = 0.6  # below this share of word-like tokens, a Latin-script page is suspicious
BAD_CHARS_MAX = 0.03  # above this share of replacement/private-use/control characters
DISAGREE = 0.5  # agreement below this means the text layer is wrong for the page
MIN_OCR_CONF = 0.6  # ...if OCR itself is at least this confident


def _bad_char(ch: str) -> bool:
    o = ord(ch)
    return ch == "�" or 0xE000 <= o <= 0xF8FF or (o < 32 and ch not in "\t\n\r")


def plausibility(text: str) -> float:
    """0-1: how much this looks like real text. Non-Latin scripts are not judged (1.0)."""
    if not text.strip():
        return 1.0
    bad = sum(_bad_char(c) for c in text) / len(text)
    if bad > BAD_CHARS_MAX:
        return 0.0
    latin = [t for t in _TOKEN.findall(text) if _LATIN.search(t)]
    tokens = [t for t in latin if len(t) >= 2]
    if len(tokens) < 5:
        return 1.0
    wordlike = sum(
        1 for t in tokens if t.isdigit() or (_VOWEL.search(t) and not _CONSONANT_RUN.search(t))
    )
    score = wordlike / len(tokens)
    if len(latin) >= 30:
        function = sum(t.lower() in FUNCTION_WORDS for t in latin) / len(latin)
        score = (
            min(score, function / FUNCTION_MIN * WORDLIKE_MIN) if function < FUNCTION_MIN else score
        )
    return score


def suspicious(words: list[Word]) -> bool:
    return plausibility(" ".join(w.text for w in words)) < WORDLIKE_MIN


def _tokens(words: list[Word]) -> Counter[str]:
    return Counter(t.lower() for w in words for t in _TOKEN.findall(w.text))


@dataclass
class PageCheck:
    page: int
    support: float
    coverage: float
    ocr_confidence: float | None
    used_ocr: bool = False
    reason: str = ""  # "suspicious text" or "sample"

    @property
    def agreement(self) -> float:
        return self.support * self.coverage**0.5


def compare(layer: list[Word], ocr: list[Word]) -> tuple[float, float]:
    """(support, coverage) of the text layer against the OCR reading."""
    a, b = _tokens(layer), _tokens(ocr)
    matched = sum((a & b).values())
    support = matched / max(sum(a.values()), 1)
    coverage = matched / max(sum(b.values()), 1)
    return support, coverage


def should_replace(check: PageCheck) -> bool:
    return check.agreement < DISAGREE and (check.ocr_confidence or 0.0) >= MIN_OCR_CONF


__all__ = ["PageCheck", "compare", "plausibility", "should_replace", "suspicious"]
