from __future__ import annotations

from pathlib import Path

from gleanly import load
from gleanly.clean import extract_html, markdown_to_plain, parse_html
from gleanly.clean.comments import with_comments
from gleanly.clean.html import Extraction, RawBlock
from gleanly.models import BlockType

PROSE = (
    "The committee met on Tuesday to discuss the new budget, which had been delayed for "
    "several weeks because of disagreements about funding for schools and roads."
)
COMMENT = (
    "I went to the meeting myself and the room was packed. Most people wanted the road "
    "money spent on the bridge first, which nobody on the committee mentioned."
)


def _page(body_class: str = "") -> str:
    article = "".join(f"<p>{PROSE} Paragraph {i}.</p>" for i in range(6))
    comments = "".join(
        f'<li class="comment"><span class="author">reader{i}</span> <span>2 hours ago</span>'
        f"<p>{COMMENT} Comment {i}.</p><a href='#r{i}'>Reply</a></li>"
        for i in range(3)
    )
    form = (
        '<form id="commentform"><p>Your email address will not be published. Required '
        "fields are marked with a star and you must log in first.</p><textarea></textarea>"
        "</form>"
    )
    return (
        f'<html><body class="{body_class}"><article>{article}</article>'
        f'<section id="comments"><h3>3 comments</h3><ol class="comment-list">{comments}</ol>'
        f"{form}</section><footer>Copyright 2025</footer></body></html>"
    )


def _text(ex: Extraction) -> str:
    return "\n".join(markdown_to_plain(b.text) for b in ex.blocks)


def test_comments_are_off_by_default() -> None:
    ex = extract_html(parse_html(_page()), None)
    assert "packed" not in _text(ex)
    assert all(b.role == "main" for b in ex.blocks)


def test_comments_appended_after_main_content() -> None:
    ex = extract_html(parse_html(_page()), None, include_comments=True)
    roles = [b.role for b in ex.blocks]
    assert roles.count("comment") == 3
    assert roles == sorted(roles, key=lambda r: r == "comment")  # main first, then comments
    text = _text(ex)
    assert "Comment 2." in text
    assert "Reply" not in text  # furniture around each comment is dropped
    assert "email address" not in text  # so is the reply form


def test_comments_open_body_class_does_not_swallow_page() -> None:
    ex = extract_html(parse_html(_page("single comments-open")), None, include_comments=True)
    assert [b.role for b in ex.blocks].count("comment") == 3
    assert "Copyright" not in _text(ex)


def test_comments_added_to_embedded_text() -> None:
    root = parse_html(_page())
    embedded = Extraction([RawBlock(BlockType.PARAGRAPH, PROSE, "$.articleBody")], "embedded")
    out = with_comments(embedded, root)
    assert [b.role for b in out.blocks].count("comment") == 3
    assert out.word_count > len(PROSE.split())


def test_load_marks_comment_blocks(tmp_path: Path) -> None:
    page = tmp_path / "post.html"
    page.write_text(_page(), encoding="utf-8")
    plain = load(str(page))
    with_c = load(str(page), include_comments=True)
    assert all(b.role == "main" for b in plain.blocks)
    assert [b.role for b in with_c.blocks].count("comment") == 3
    assert "packed" in with_c.markdown
