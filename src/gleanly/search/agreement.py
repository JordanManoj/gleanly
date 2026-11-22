"""Cross-source agreement for search results (v0: numeric and date facts).

The most common, checkable contradictions between web sources are numbers: years,
dates, quantities, percentages, prices. For every fetched result this module

1. splits the page into sentences that mention the query (keeping where each came from:
   URL, block and character span in the Markdown),
2. extracts numeric facts, each with its context (the content words around it),
3. compares facts from *different* sources: when their contexts match, the same value
   corroborates the fact and different values are a conflict.

Each finding quotes every source with its location, so a reader (or a RAG pipeline) can
check it. This is a heuristic first version: it does not understand paraphrase or
non-numeric claims, and it reports candidates for review, not verdicts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gleanly.models import (
    AgreementReport,
    ClaimSource,
    Document,
    FactGroup,
    FactValue,
)

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")
_NUMBER = re.compile(
    r"(?P<cur>[$€£])?\s?(?P<num>\d{1,3}(?:[,\u00a0]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s?(?P<unit>%|percent|per cent|million|billion|thousand|km|m|cm|mm|kg|g|t|"
    r"metres|meters|feet|ft|miles|mi|years|year|people|km2|sq km)?\b",
    re.IGNORECASE,
)
_STOP_TEXT = (
    "the a an and or of to in on at by for from with as is are was were be been it its this "
    "that these those which who than then there their about also more most over under into "
    "after before during between some many much other such only very can could would should "
    "has have had not but all any each per"
)
_STOP = frozenset(_STOP_TEXT.split())
_MONTHS_TEXT = (
    "january february march april may june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec"
)
_MONTHS = frozenset(_MONTHS_TEXT.split())
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+|www\.\S+")
# Footnote markers ([12], [a], [note 3]) are citation numbers, not facts.
_FOOTNOTE = re.compile(r"\[(?:\d{1,4}|[a-z]|note \d+|citation needed)\]", re.IGNORECASE)
_MARKS = re.compile(r"[*_`|#>]+")
# Citation and reference lines: their numbers are page ids, dates and ISBNs, not facts.
_CITATION = re.compile(
    r"\b(retrieved|isbn|issn|doi|oclc|pmid|archived|accessed)\b|\u2191", re.IGNORECASE
)
CONTEXT_WINDOW = 4  # content words on each side of a number (query words excluded)
# Two facts are about the same thing when they share the anchor word and at least
# MIN_SHARED context words in all, or when their contexts overlap at least STRONG_MATCH.
# Strict on purpose: a false conflict hurts trust more than a missed one.
MIN_SHARED = 2
STRONG_MATCH = 0.75
# A conflict also needs the two sentences to say nearly the same thing apart from the
# number (overlap of their content words): different events that merely share a phrase
# ("reached the summit in 1963" / "... in 1994") must not be reported as contradictions.
CONFLICT_SENTENCE_MATCH = 0.6
REL_TOLERANCE = 0.005  # values within 0.5% count as the same (rounding)
MAX_GROUPS = 10


def _stem(w: str) -> str:
    """Lower-case and fold plurals; stop words are dropped before folding."""
    w = w.lower()
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


@dataclass
class _Fact:
    value: float
    kind: str  # "year", "percent", "currency:$", "unit:km", "number"
    text: str  # the value as written
    context: frozenset[str]
    anchor: str  # nearest content word before the number (else after): what it measures
    words: frozenset[str]  # content words of the whole sentence (query words excluded)
    source: ClaimSource
    doc: int


def _kind(m: re.Match[str], value: float) -> str:
    unit = (m.group("unit") or "").lower()
    if m.group("cur"):
        return f"currency:{m.group('cur')}"
    if unit in ("%", "percent", "per cent"):
        return "percent"
    if unit in ("million", "billion", "thousand"):
        return f"scale:{unit}"
    if unit:
        return f"unit:{unit}"
    if value.is_integer() and 1000 <= value <= 2100 and "," not in m.group("num"):
        return "year"
    return "number"


def _sentences(doc: Document) -> list[tuple[int, int, str]]:
    """(block index, char start in the Markdown, sentence text) for prose blocks."""
    out = []
    for i, block in enumerate(doc.blocks):
        if block.type in ("code", "image"):
            continue
        start = block.provenance.char_start
        offset = 0
        for part in _SENT.split(block.text):
            pos = block.text.find(part, offset)
            offset = pos + len(part)
            out.append((i, start + max(pos, 0), part.strip()))
    return out


def _content(text: str) -> list[str]:
    """Content words in order: stop words removed first, then plurals folded."""
    return [_stem(w) for w in _WORD.findall(text) if w.lower() not in _STOP]


def _plain(sentence: str) -> str:
    """Sentence text without image links, link targets, URLs and Markdown marks."""
    text = _IMAGE.sub(" ", sentence)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    text = _FOOTNOTE.sub(" ", text)
    return _MARKS.sub(" ", text)


def _junk_number(m: re.Match[str], raw: str, value: float) -> bool:
    """Ids, list indices and other numbers that are not facts."""
    if m.group("cur") or m.group("unit"):
        return False
    digits = raw.replace(".", "")
    if len(digits) > 7 or (raw.startswith("0") and len(raw) > 1):
        return True
    return value < 10


def extract_facts(doc: Document, doc_index: int, url: str, query_terms: set[str]) -> list[_Fact]:
    facts = []
    for block_i, char_start, quote in _sentences(doc):
        if _CITATION.search(quote):
            continue
        sent = _plain(quote)
        words = [_stem(w) for w in _WORD.findall(sent)]
        if query_terms and not query_terms & set(words):
            continue  # only sentences about the query
        for m in _NUMBER.finditer(sent):
            raw = m.group("num").replace(",", "").replace("\u00a0", "")
            try:
                value = float(raw)
            except ValueError:
                continue
            if _junk_number(m, raw, value):
                continue
            before = _content(sent[: m.start()])
            after = _content(sent[m.end() :])
            near = (before[-1:] + after[:1]) if (before or after) else []
            if value.is_integer() and value <= 31 and _MONTHS & set(near):
                continue  # the day of a date ("30 March 1885")
            skip = query_terms | _MONTHS  # query words are in every sentence
            left = [w for w in before if w not in skip][-CONTEXT_WINDOW:]
            right = [w for w in after if w not in skip][:CONTEXT_WINDOW]
            context = left + right
            if len(context) < 2:
                continue
            anchor = left[-1] if left else right[0]
            facts.append(
                _Fact(
                    value,
                    _kind(m, value),
                    m.group(0).strip(),
                    frozenset(context),
                    anchor,
                    frozenset(w for w in _content(sent) if w not in skip),
                    ClaimSource(
                        url=url,
                        block_index=block_i,
                        char_start=char_start,
                        char_end=char_start + len(quote),
                        quote=quote[:300],
                    ),
                    doc_index,
                )
            )
    return facts


def _same(a: _Fact, b: _Fact) -> bool:
    if a.kind == "year" or b.kind == "year":
        return a.value == b.value
    top = max(abs(a.value), abs(b.value), 1e-9)
    return abs(a.value - b.value) / top <= REL_TOLERANCE


def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def _about_same(a: _Fact, b: _Fact) -> bool:
    """Same kind of value, and the same anchor plus another shared word, or a strong
    context overlap."""
    if a.kind != b.kind:
        return False
    if a.anchor == b.anchor and len(a.context & b.context) >= MIN_SHARED:
        return True
    return _overlap(a.context, b.context) >= STRONG_MATCH


def _contradicts(values: list[list[_Fact]]) -> bool:
    """Two different values, from different sources, in nearly the same sentence."""
    for i, va in enumerate(values):
        for vb in values[i + 1 :]:
            for a in va:
                for b in vb:
                    if a.doc != b.doc and _overlap(a.words, b.words) >= CONFLICT_SENTENCE_MATCH:
                        return True
    return False


def compare(facts: list[_Fact]) -> AgreementReport:
    """Group facts about the same thing (from different sources) into agreements/conflicts."""
    groups: list[list[_Fact]] = []
    for f in facts:
        for g in groups:
            if _about_same(g[0], f):
                g.append(f)
                break
        else:
            groups.append([f])

    corroborated: list[FactGroup] = []
    conflicts: list[FactGroup] = []
    for g in groups:
        if len({f.doc for f in g}) < 2:
            continue  # needs at least two different sources
        per_doc: dict[int, set[float]] = {}
        for f in g:
            per_doc.setdefault(f.doc, set()).add(f.value)
        if any(len(v) > 1 for v in per_doc.values()):
            continue  # a source that gives several values here is ambiguous
        values: list[list[_Fact]] = []
        for f in g:
            for v in values:
                if _same(v[0], f):
                    v.append(f)
                    break
            else:
                values.append([f])
        shared = set.intersection(*(set(f.context) for f in g)) or set(g[0].context)
        topic = " ".join(sorted(shared))
        group = FactGroup(
            topic=topic[:120],
            kind=g[0].kind,
            values=[
                FactValue(value=v[0].text, sources=[f.source for f in v])
                for v in sorted(values, key=len, reverse=True)
            ],
        )
        if len(values) == 1:
            corroborated.append(group)
        elif _contradicts(values):
            conflicts.append(group)
    by_support = lambda grp: -sum(len(v.sources) for v in grp.values)  # noqa: E731
    return AgreementReport(
        conflicts=sorted(conflicts, key=by_support)[:MAX_GROUPS],
        corroborated=sorted(corroborated, key=by_support)[:MAX_GROUPS],
    )


def check_agreement(query: str, docs: list[tuple[str, Document]]) -> AgreementReport:
    """Agreement report over fetched search results: (url, document) pairs."""
    terms = {_stem(w) for w in _WORD.findall(query)} - _STOP
    facts: list[_Fact] = []
    for i, (url, doc) in enumerate(docs):
        facts += extract_facts(doc, i, url, terms)
    return compare(facts)


__all__ = ["check_agreement", "compare", "extract_facts"]
