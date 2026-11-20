"""Main-content extraction and HTML -> Markdown conversion.

The tree is never mutated, so every emitted block keeps the XPath of its source
element in the original document (block-level provenance).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from urllib.parse import urljoin

from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]
from lxml import html as lxml_html
from lxml.html import HtmlElement

from gleanly.models import BlockType

_WS = re.compile(r"\s+")
_HSPACE = re.compile(r"[ \t\f\v\r]+")
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.I)
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MD_MARKS = re.compile(r"[*`#>|]+")
_LANG_CLASS = re.compile(r"(?:language|lang)-([\w+#.-]+)", re.I)

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "header", "footer", "aside", "nav",
    "ul", "ol", "dl", "pre", "table", "blockquote", "figure", "figcaption", "hr",
    "details", "summary", "address", "center", "fieldset", "li", "dt", "dd",
    "tr", "td", "th", "tbody", "thead", "tfoot", "caption", "body", "html",
} | HEADINGS  # fmt: skip
SKIP_TAGS = {
    "script", "style", "noscript", "template", "svg", "nav", "aside", "iframe",
    "button", "select", "input", "textarea", "canvas", "dialog", "object", "embed",
    "head", "title", "meta", "link", "math",
}  # fmt: skip
SKIP_ROLES = {"navigation", "contentinfo", "complementary", "search", "dialog", "alertdialog",
              "menu", "menubar", "toolbar", "banner"}  # fmt: skip
BOILERPLATE_WORDS = {
    "nav", "navbar", "navigation", "menu", "footer", "sidebar", "breadcrumb", "breadcrumbs",
    "cookie", "cookies", "consent", "gdpr", "banner", "advert", "advertisement", "ad", "ads",
    "promo", "promotion", "promotional", "sponsored", "share", "sharing", "social", "related",
    "newsletter", "subscribe",
    "comment", "comments", "popup", "modal", "masthead", "topbar", "toolbar", "pagination",
    "skip", "sr-only", "visually-hidden",
}  # fmt: skip
NEVER_HINT = {"html", "body", "main", "article"}
_PARA_TAGS = {"p", "pre", "blockquote"}
_LINK_CHECKED = {"ul", "ol", "div", "section", "table", "dl"}
# Class/id words that suggest real content. A boilerplate word next to one of these
# ("post-share-wrapper" vs "article-content has-share") is not trusted on its own.
CONTENT_WORDS = {
    "article", "content", "post", "entry", "story", "body", "text", "main", "blog", "prose",
    "column", "page",
}  # fmt: skip
# Words that mark boilerplate no matter what else the class says.
STRONG_BOILERPLATE = {
    "nav", "navbar", "navigation", "menu", "footer", "breadcrumb", "breadcrumbs", "cookie",
    "cookies", "consent", "gdpr", "newsletter", "popup", "modal", "sidebar",
}  # fmt: skip
# A hinted element holding at least this much non-link text is kept regardless of its name.
SUBSTANTIAL_TEXT = 500
# How far up from the best block to look for repeated copies of it (split articles).
LOOKALIKE_LEVELS = 3
CAPTION_WORDS = {"caption", "credit", "credits"}
BYLINE_WORDS = {"byline", "dateline", "timestamp", "tags", "author", "date"}
# Forms with less text than this are search boxes, logins or sign-ups.
FORM_TEXT = 500


@dataclass
class RawBlock:
    type: BlockType
    text: str
    dom_path: str | None
    level: int | None = None
    kind: str = "html"
    support: float | None = None
    role: str = "main"  # "main" content or a reader "comment"


@dataclass
class Extraction:
    blocks: list[RawBlock]
    method: str
    link_chars: int = 0
    page_chars: int = 0
    extractor: str = "main"  # "main" (container scoring) or "blocks" (block classifier)
    content_chars: int = field(init=False)
    word_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        plain = " ".join(markdown_to_plain(b.text) for b in self.blocks)
        self.content_chars = len(plain)
        self.word_count = len(plain.split())


def markdown_to_plain(md: str) -> str:
    text = md
    while True:  # nested constructs such as [![alt](img)](link) need several passes
        stripped = _MD_LINK.sub(r"\1", text)
        if stripped == text:
            break
        text = stripped
    text = _MD_MARKS.sub("", text)
    return _WS.sub(" ", text).strip()


def parse_html(text: str) -> HtmlElement:
    text = _XML_DECL.sub("", text)
    if not text.strip():
        text = "<html><body></body></html>"
    try:
        return lxml_html.document_fromstring(text)
    except (etree.ParserError, ValueError):
        return lxml_html.document_fromstring("<html><body></body></html>")


def _norm(text: str | None) -> str:
    return _WS.sub(" ", text) if text else ""


def _clean_lines(text: str) -> str:
    lines = (_HSPACE.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def _is_element(node: object) -> bool:
    return isinstance(getattr(node, "tag", None), str)


class HtmlExtractor:
    def __init__(
        self,
        root: HtmlElement,
        base_url: str | None,
        *,
        path_prefix: str = "",
        kind: str = "html",
    ) -> None:
        self.root = root
        self.tree = root.getroottree()
        self.base_url = base_url
        base = root.find(".//base[@href]")
        if base is not None:
            href = base.get("href") or ""
            self.base_url = urljoin(base_url, href) if base_url else href or None
        self.path_prefix = path_prefix
        self.kind = kind
        self.blocks: list[RawBlock] = []
        self.link_chars = 0
        self._container: HtmlElement | None = None
        self._hint_cache: dict[HtmlElement, bool] = {}
        self._link_cache: dict[HtmlElement, bool] = {}
        self._density_cache: dict[HtmlElement, float] = {}
        self._keep_roots: set[HtmlElement] = set()
        self._keep_path: set[HtmlElement] = set()
        self._lca: HtmlElement | None = None

    # ------------------------------------------------------------------ public
    def extract(self, method: str = "http", *, include_comments: bool = False) -> Extraction:
        body = self.root.find("body")
        if body is None:
            body = self.root
        container = self._choose_container(body)
        self._container = container
        self._flow(container)
        if include_comments:
            from gleanly.clean.comments import comment_blocks, comment_sections

            def extracted(el: HtmlElement) -> bool:
                inside = any(a is container for a in el.iterancestors())
                return inside and not self._skipped_or_under_skipped(el, container)

            self.blocks += comment_blocks(comment_sections(body, container, extracted))
        page_chars = len(_norm(self._visible_text(body, skip=False)).strip())
        return Extraction(self.blocks, method, link_chars=self.link_chars, page_chars=page_chars)

    # --------------------------------------------------------------- skipping
    def _is_skipped(self, el: HtmlElement) -> bool:
        tag = el.tag
        if tag in SKIP_TAGS:
            return True
        if el is self._container:
            return False
        if self._keep_roots and el is not self._lca:
            parent = el.getparent()
            on_path = el in self._keep_roots or el in self._keep_path
            if not on_path and (parent is self._lca or parent in self._keep_path):
                return True
        if tag == "footer":
            return True
        if self._is_meta(el):
            return True
        if tag == "form":  # search boxes, logins; but some CMSs wrap the whole page in one
            return len(_norm(el.text_content()).strip()) < FORM_TEXT
        if tag == "header":
            return not self._inside_content(el)
        if el.get("hidden") is not None or el.get("aria-hidden") == "true":
            return True
        style = (el.get("style") or "").replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            return True
        if (el.get("role") or "").lower() in SKIP_ROLES:
            return True
        if tag in _LINK_CHECKED and self._link_heavy(el):
            return True
        if tag not in NEVER_HINT:
            return self._hinted_boilerplate(el)
        return False

    def _is_meta(self, el: HtmlElement) -> bool:
        """Captions, bylines, datelines and tag lists: page furniture, not article text."""
        if el.tag == "figcaption":
            return True
        hint = f"{el.get('class') or ''} {el.get('id') or ''}".lower()
        if not hint.strip():
            return False
        parts = {part for w in re.split(r"[\s_]+", hint) for part in w.split("-")}
        if not parts & (CAPTION_WORDS | BYLINE_WORDS):
            return False
        # A wrapper such as WordPress' "hentry post author-admin" holds the whole post.
        has_title = el.find(".//h1") is not None or el.find(".//h2") is not None
        if has_title and any(len(_norm(p.text_content()).strip()) >= 80 for p in el.iter("p")):
            return False
        if parts & CAPTION_WORDS:
            return len(_norm(el.text_content())) < 400
        if parts & BYLINE_WORDS:  # kept in Document.metadata instead
            return len(_norm(el.text_content())) < 200
        return False

    def _link_heavy(self, el: HtmlElement) -> bool:
        """Related-story strips, share bars, video carousels: mostly links or images.

        Elements that contain the chosen content container are never removed.
        """
        container = self._container
        if container is None:  # still choosing the container: only prune inside it later
            return False
        cached = self._link_cache.get(el)
        if cached is not None:
            return cached
        result = False
        if not any(a is el for a in container.iterancestors()):
            text = _norm(el.text_content()).strip()
            links = list(el.iter("a"))
            if links or el.find(".//img") is not None:
                link_text = sum(len(_norm(a.text_content()).strip()) for a in links)
                own = len(text) - link_text
                if own < 20:  # nothing but links/images
                    result = True
                elif text and link_text / len(text) > 0.5 and len(links) >= 2:
                    # ...unless real prose sits next to the links (article + link sidebar).
                    result = self._prose_paragraphs(el) < 3
        self._link_cache[el] = result
        return result

    def _hinted_boilerplate(self, el: HtmlElement) -> bool:
        """Class/id names are a hint, weighed against how much real text the element holds.

        Real sites put words like "share" or "consent" on wrappers around the whole
        article, so a name alone must not discard a large, prose-heavy element.
        """
        cached = self._hint_cache.get(el)
        if cached is not None:
            return cached
        result = False
        hint = f"{el.get('class') or ''} {el.get('id') or ''}".lower()
        if hint.strip():
            words = set(re.split(r"[\s_]+", hint))
            parts = {part for w in words for part in w.split("-")}
            bad = parts & BOILERPLATE_WORDS
            if bad:
                # Per class token: "share-buttons" is boilerplate, while a body class like
                # "mm-use-consent-management-enabled" sits beside real content tokens.
                strong = any(
                    set(w.split("-")) & STRONG_BOILERPLATE and not set(w.split("-")) & CONTENT_WORDS
                    for w in words
                )
                positive = bool(parts & CONTENT_WORDS)
                if positive:
                    # "l-sidebar-fixed l-article-body-segment": the content word wins
                    # unless the element is tiny (e.g. "article-share" with three links).
                    result = len(_norm(el.text_content()).strip()) < 200
                elif strong:
                    result = not self._is_substantial(el, strict=True)
                else:
                    result = not self._is_substantial(el)
        self._hint_cache[el] = result
        return result

    @staticmethod
    def _prose_paragraphs(el: HtmlElement) -> int:
        """Paragraphs of at least 80 characters that are mostly not link text."""
        count = 0
        for p in el.iter("p"):
            text = _norm(p.text_content()).strip()
            if len(text) < 80:
                continue
            link_text = sum(len(_norm(a.text_content()).strip()) for a in p.iter("a"))
            if link_text / len(text) < 0.5:
                count += 1
        return count

    @staticmethod
    def _is_substantial(el: HtmlElement, *, strict: bool = False) -> bool:
        """Lots of prose and few links: this element carries content."""
        text = _norm(el.text_content()).strip()
        if len(text) < SUBSTANTIAL_TEXT * (4 if strict else 1):
            return False
        link_text = sum(len(_norm(a.text_content()).strip()) for a in el.iter("a"))
        paragraphs = sum(1 for p in el.iter("p") if len(_norm(p.text_content()).strip()) >= 80)
        return link_text / len(text) < 0.3 and paragraphs >= (5 if strict else 3)

    @staticmethod
    def _inside_content(el: HtmlElement) -> bool:
        return any(
            a.tag in ("article", "main") or a.get("role") == "main" for a in el.iterancestors()
        )

    def _skipped_or_under_skipped(self, el: HtmlElement, stop: HtmlElement) -> bool:
        node: HtmlElement | None = el
        while node is not None and node is not stop:
            if self._is_skipped(node):
                return True
            node = node.getparent()
        return False

    def _visible_text(self, el: HtmlElement, *, skip: bool = True) -> str:
        parts: list[str] = []

        def rec(e: HtmlElement) -> None:
            if e.text:
                parts.append(e.text)
            for child in e:
                if _is_element(child):
                    hidden = child.tag in SKIP_TAGS or (skip and self._is_skipped(child))
                    if not hidden:
                        rec(child)
                if child.tail:
                    parts.append(child.tail)

        rec(el)
        return " ".join(parts)

    # -------------------------------------------------------------- container
    def _choose_container(self, body: HtmlElement) -> HtmlElement:
        """Pick the element that holds the main content.

        Every paragraph-like element votes for its parent (full weight), grandparent (1/2)
        and great-grandparent (1/6) with a score from its length and comma count. Each
        candidate starts from a tag and class/id prior and is scaled by (1 - link density).
        Siblings of the winner that also look like content are kept with it.
        """
        scores: dict[HtmlElement, float] = {}
        for p in self._paragraph_like(body):
            if self._skipped_or_under_skipped(p, body):
                continue
            text = _norm(p.text_content() if p.tag in _PARA_TAGS else self._own_text(p)).strip()
            if len(text) < 25:
                continue
            commas = text.count(",") + text.count("，")  # noqa: RUF001 (fullwidth CJK comma)
            value = 1 + commas + min(len(text) // 100, 3)
            for level, anc in enumerate(list(p.iterancestors())[:3]):
                if anc is body.getparent():
                    break
                if anc not in scores:
                    scores[anc] = self._prior(anc)
                scores[anc] += value / (1, 2, 6)[level]
        if not scores:
            return body
        final = {el: sc * (1 - self._link_density(el)) for el, sc in scores.items()}
        top = max(final, key=lambda e: final[e])
        return self._with_siblings(top, final)

    def _with_siblings(self, top: HtmlElement, final: dict[HtmlElement, float]) -> HtmlElement:
        """Add siblings and look-alike cousins that also hold content (split articles)."""
        parent = top.getparent()
        if parent is None or parent.tag in ("html",):
            return top
        threshold = max(10.0, final[top] * 0.2)
        keep: set[HtmlElement] = {top}
        for sib in parent:
            if sib is top or not _is_element(sib) or sib.tag in SKIP_TAGS:
                continue
            if final.get(sib, 0.0) >= threshold:
                keep.add(sib)
            elif sib.tag == "p":
                text = _norm(sib.text_content()).strip()
                density = self._link_density(sib)
                if (len(text) >= 80 and density < 0.25) or (
                    0 < len(text) < 80 and density == 0 and re.search(r"\.( |$)", text)
                ):
                    keep.add(sib)
        keep |= self._lookalikes(top)
        if len(keep) == 1:
            return top
        return self._restrict_to(keep)

    def _lookalikes(self, top: HtmlElement) -> set[HtmlElement]:
        """Repeated containers with the same tag and class as ``top`` (split articles).

        Sites such as NYT or Wired wrap every few paragraphs in a new copy of the same
        container; each copy that holds prose belongs to the article.
        """
        cls = top.get("class")
        if not cls:
            return set()
        found: set[HtmlElement] = set()
        for anc in list(top.iterancestors())[:LOOKALIKE_LEVELS]:
            if anc.tag in ("body", "html"):
                break
            for el in anc.iter(top.tag):
                if el is top or el.get("class") != cls or el in found:
                    continue
                if self._is_skipped(el) or self._link_density(el) >= 0.5:
                    continue
                if self._prose_chars(el) >= 80:
                    found.add(el)
        return found

    def _restrict_to(self, keep: set[HtmlElement]) -> HtmlElement:
        """Use the closest common ancestor of ``keep`` and skip everything off-path."""
        chains = [[k, *k.iterancestors()] for k in keep]
        common = set(chains[0])
        for chain in chains[1:]:
            common &= set(chain)
        lca = next(a for a in chains[0] if a in common)
        path: set[HtmlElement] = set()
        for k in keep:
            for a in k.iterancestors():
                if a is lca:
                    break
                path.add(a)
        self._keep_roots, self._keep_path, self._lca = keep, path, lca
        return lca

    def _prose_chars(self, el: HtmlElement) -> int:
        """Characters in <p> paragraphs that read like prose (long enough, few links)."""
        total = 0
        for p in el.iter("p"):
            text = _norm(p.text_content()).strip()
            if len(text) >= 40 and self._link_density(p) < 0.5:
                total += len(text)
        return total

    def _prior(self, el: HtmlElement) -> float:
        """Starting score from the tag and from class/id words."""
        tag = el.tag
        score = {"div": 5.0, "article": 10.0, "main": 5.0, "section": 3.0, "pre": 3.0,
                 "td": 3.0, "blockquote": 3.0}.get(tag, 0.0)  # fmt: skip
        if tag in ("address", "ol", "ul", "dl", "dd", "dt", "li", "form"):
            score -= 3
        elif tag in HEADINGS or tag == "th":
            score -= 5
        for attr in ("class", "id"):
            value = (el.get(attr) or "").lower()
            if not value:
                continue
            parts = {part for w in re.split(r"[\s_]+", value) for part in w.split("-")}
            if parts & CONTENT_WORDS:
                score += 25
            if parts & BOILERPLATE_WORDS:
                score -= 25
        return score

    def _link_density(self, el: HtmlElement) -> float:
        cached = self._density_cache.get(el)
        if cached is None:
            text = len(_norm(el.text_content()).strip())
            links = sum(len(_norm(a.text_content()).strip()) for a in el.iter("a"))
            cached = links / text if text else 0.0
            self._density_cache[el] = cached
        return cached

    @staticmethod
    def _own_text(el: HtmlElement) -> str:
        """Text that belongs to ``el`` itself: its text, inline children and tails."""
        parts = [el.text or ""]
        for child in el:
            if _is_element(child) and child.tag not in BLOCK_TAGS and child.tag not in SKIP_TAGS:
                parts.append(child.text_content())
            parts.append(child.tail or "")
        return " ".join(parts).strip()

    def _paragraph_like(self, body: HtmlElement) -> Iterator[HtmlElement]:
        """<p>, <pre>, <blockquote>, plus <div>/<section>/<td> that hold prose directly.

        Many CMSs (CNN, forums, older blogs) use <div> or <br>-separated text instead of <p>.
        """
        for el in body.iter():
            if not _is_element(el):
                continue
            if el.tag in _PARA_TAGS or (
                el.tag in ("div", "section", "td") and len(_norm(self._own_text(el))) >= 25
            ):
                yield el

    # ------------------------------------------------------------- emission
    def _path(self, el: HtmlElement) -> str:
        path = self.tree.getpath(el)
        return f"{self.path_prefix}{path}" if self.path_prefix else path

    def _emit(self, btype: BlockType, text: str, el: HtmlElement, level: int | None = None) -> None:
        text = text.strip()
        if text:
            self.blocks.append(RawBlock(btype, text, self._path(el), level, self.kind))

    def _emit_paragraph(self, text: str, el: HtmlElement) -> None:
        text = _clean_lines(text)
        if not text:
            return
        btype = BlockType.IMAGE if re.fullmatch(r"!\[[^\]]*\]\([^)]*\)", text) else None
        self._emit(btype or BlockType.PARAGRAPH, text, el)

    # ------------------------------------------------------------ block flow
    def _flow(self, el: HtmlElement) -> None:
        """Walk a container: block children become blocks, loose inline runs paragraphs."""
        buf: list[str] = [_norm(el.text)]
        for child in el:
            if _is_element(child) and not self._is_skipped(child):
                if child.tag in BLOCK_TAGS:
                    self._emit_paragraph("".join(buf), el)
                    buf = []
                    self._block(child)
                else:
                    buf.append(self._inline_node(child))
            buf.append(_norm(child.tail))
        self._emit_paragraph("".join(buf), el)

    def _block(self, el: HtmlElement) -> None:
        tag = el.tag
        if tag in HEADINGS:
            level = int(tag[1])
            text = markdown_to_plain(self._inline_children(el))
            if text:
                self._emit(BlockType.HEADING, f"{'#' * level} {text}", el, level)
        elif tag == "p":
            self._emit_paragraph(self._inline_children(el), el)
        elif tag in ("ul", "ol"):
            self._emit(BlockType.LIST, self._render_list(el, 0), el)
        elif tag == "dl":
            self._emit(BlockType.LIST, self._render_dl(el), el)
        elif tag == "pre":
            self._emit(BlockType.CODE, self._render_pre(el), el)
        elif tag == "table":
            self._table(el)
        elif tag == "blockquote":
            self._blockquote(el)
        elif tag == "hr":
            return
        else:
            self._flow(el)

    def _render_pre(self, el: HtmlElement) -> str:
        code = el.find(".//code")
        lang = ""
        for node in (code, el):
            if node is not None and (m := _LANG_CLASS.search(node.get("class") or "")):
                lang = m.group(1)
                break
        text = el.text_content().strip("\n")
        fence = "```"
        while fence in text:
            fence += "`"
        return f"{fence}{lang}\n{text}\n{fence}"

    def _render_list(self, el: HtmlElement, depth: int) -> str:
        ordered = el.tag == "ol"
        try:
            n = int(el.get("start") or 1)
        except ValueError:
            n = 1
        lines: list[str] = []
        for li in el:
            if not _is_element(li) or li.tag != "li" or self._is_skipped(li):
                continue
            nested: list[HtmlElement] = []
            text = _clean_lines(self._inline_children(li, nested_lists=nested)).replace("\n", " ")
            marker = f"{n}." if ordered else "-"
            n += 1
            lines.append(f"{'  ' * depth}{marker} {text}".rstrip())
            for sub in nested:
                rendered = self._render_list(sub, depth + 1)
                if rendered:
                    lines.append(rendered)
        return "\n".join(lines)

    def _render_dl(self, el: HtmlElement) -> str:
        lines: list[str] = []
        for child in el:
            if not _is_element(child) or self._is_skipped(child):
                continue
            text = _clean_lines(self._inline_children(child)).replace("\n", " ")
            if not text:
                continue
            if child.tag == "dt":
                lines.append(f"**{markdown_to_plain(text)}**")
            elif child.tag == "dd":
                lines.append(f": {text}")
        return "\n".join(lines)

    def _table(self, el: HtmlElement) -> None:
        if el.find(".//table") is not None:  # layout table: treat as a container
            self._flow(el)
            return
        rows: list[list[str]] = []
        for tr in el.iter("tr"):
            row: list[str] = []
            for cell in tr:
                if not _is_element(cell) or cell.tag not in ("td", "th"):
                    continue
                text = _clean_lines(self._inline_children(cell)).replace("\n", " ")
                row.append(text.replace("|", "\\|"))
                try:
                    span = int(cell.get("colspan") or 1)
                except ValueError:
                    span = 1
                row.extend([""] * (min(span, 50) - 1))
            if any(row):
                rows.append(row)
        if not rows:
            return
        width = max(len(r) for r in rows)
        if width == 1:  # single-column tables are layout, not data
            self._flow(el)
            return
        caption = el.find("caption")
        if caption is not None:
            self._emit_paragraph(self._inline_children(caption), caption)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        self._emit(BlockType.TABLE, "\n".join(lines), el)

    def _blockquote(self, el: HtmlElement) -> None:
        saved = self.blocks
        self.blocks = []
        self._flow(el)
        inner, self.blocks = self.blocks, saved
        text = "\n\n".join(b.text for b in inner)
        quoted = "\n".join(f"> {line}" if line else ">" for line in text.split("\n"))
        self._emit(BlockType.QUOTE, quoted, el)

    # -------------------------------------------------------------- inline
    def _inline_children(
        self, el: HtmlElement, nested_lists: list[HtmlElement] | None = None
    ) -> str:
        parts = [_norm(el.text)]
        for child in el:
            if _is_element(child) and not self._is_skipped(child):
                if nested_lists is not None and child.tag in ("ul", "ol"):
                    nested_lists.append(child)
                else:
                    parts.append(self._inline_node(child, nested_lists))
            parts.append(_norm(child.tail))
        return "".join(parts)

    @staticmethod
    def _wrap(inner: str, left: str, right: str | None = None) -> str:
        core = inner.strip()
        if not core:
            return inner
        lead = " " if inner[:1].isspace() else ""
        trail = " " if inner[-1:].isspace() else ""
        return f"{lead}{left}{core}{right if right is not None else left}{trail}"

    def _abs(self, url: str) -> str:
        return urljoin(self.base_url, url) if self.base_url else url

    def _inline_node(self, el: HtmlElement, nested_lists: list[HtmlElement] | None = None) -> str:
        tag = el.tag
        if tag == "br":
            return "\n"
        if tag == "img":
            src = el.get("src") or el.get("data-src") or ""
            if not src or src.startswith("data:") or el.get("width") == "1":
                return ""
            alt = _norm(el.get("alt")).strip().replace("]", "")
            return f"![{alt}]({self._abs(src)})"
        if tag in ("code", "kbd", "samp", "tt"):
            text = _norm(el.text_content())
            tick = "``" if "`" in text else "`"
            return self._wrap(text, tick)
        # Nested lists inside block wrappers (e.g. <li><div><ul>) still become sub-lists.
        inner = self._inline_children(el, nested_lists if tag in BLOCK_TAGS else None)
        if tag == "a":
            href = (el.get("href") or "").strip()
            self.link_chars += len(markdown_to_plain(inner))
            if not href or href.startswith(("javascript:", "#")) or not inner.strip():
                return inner
            return self._wrap(inner, "[", f"]({self._abs(href)})")
        if tag in ("strong", "b"):
            return self._wrap(inner, "**")
        if tag in ("em", "i", "cite"):
            return self._wrap(inner, "*")
        if tag in ("del", "s", "strike"):
            return self._wrap(inner, "~~")
        if tag in BLOCK_TAGS:
            return f" {inner} "
        return inner


def extract_html(
    root: HtmlElement,
    base_url: str | None,
    *,
    method: str = "http",
    include_comments: bool = False,
) -> Extraction:
    return HtmlExtractor(root, base_url).extract(method, include_comments=include_comments)


def extract_fragment(
    fragment_html: str, base_url: str | None, *, path_prefix: str, kind: str
) -> list[RawBlock]:
    """Extract blocks from an HTML fragment (e.g. HTML stored inside JSON)."""
    root = parse_html(f"<html><body>{fragment_html}</body></html>")
    extractor = HtmlExtractor(root, base_url, path_prefix=path_prefix, kind=kind)
    body = root.find("body")
    extractor._container = body if body is not None else root
    extractor._flow(extractor._container)
    return extractor.blocks
