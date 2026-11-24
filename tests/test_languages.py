"""Text in any language: word counts, tokens, sentence ends, pages without spaces."""

from __future__ import annotations

from pathlib import Path

from gleanly import load
from gleanly.clean.blocks import _SENTENCE_END, _needs_stop
from gleanly.clean.text import count_words, tokens

ZH = "市议会于二零二六年三月十四日批准了大桥的新预算。这座桥连接城市的南北两岸\uff0c每天有数千人通过。"
JA = "市議会は月曜日に橋の新しい予算を承認しました。この橋は町の北と南を結んでいます。"
HI = "नगर परिषद ने सोमवार को पुल के लिए नया बजट मंज़ूर किया। यह पुल शहर के दोनों हिस्सों को जोड़ता है।"
TH = "สภาเมืองอนุมัติงบประมาณใหม่สำหรับสะพานเมื่อวันจันทร์ สะพานนี้เชื่อมทั้งสองฝั่งของเมือง"


def test_spaced_languages_count_as_before() -> None:
    assert count_words("The council met on Monday.") == 5
    assert count_words("Der Stadtrat hat getagt.") == 4
    assert tokens("Hello, Wörld!") == ["hello", "wörld"]


def test_unspaced_scripts_are_counted_by_characters() -> None:
    assert count_words("市议会批准了预算") == 8  # one word per Chinese character
    assert count_words("市议会 OK") == 4  # a Latin word glued on still counts
    assert 15 <= count_words(TH) <= 25  # Thai: about four characters per word
    assert tokens("市议会") == ["市", "议", "会"]


def test_indic_words_keep_their_vowel_signs() -> None:
    assert tokens("मंज़ूर किया।") == ["मंज़ूर", "किया"]


def test_sentence_ends_in_other_scripts() -> None:
    for text in ("यह एक वाक्य है। अगला", "这是一句话。下一句", "هل هذا سؤال؟ نعم", "Done. Next"):
        assert _SENTENCE_END.search(text), text
    assert not _needs_stop(TH)  # Thai writes no sentence punctuation
    assert _needs_stop("English text")


def _page(body: str, lang: str) -> str:
    nav = "".join(f"<li><a href='/{i}'>Link {i}</a></li>" for i in range(12))
    return (
        f"<html lang='{lang}'><head><title>T</title></head><body>"
        f"<nav><ul>{nav}</ul></nav><main><h1>Title</h1>{body}</main>"
        "<footer><a href='/a'>About</a> <a href='/b'>Contact</a></footer></body></html>"
    )


def test_chinese_and_japanese_articles_are_extracted(tmp_path: Path) -> None:
    for lang, text in (("zh", ZH), ("ja", JA), ("hi", HI)):
        path = tmp_path / f"{lang}.html"
        paras = "".join(f"<p>{i}. {text}</p>" for i in range(1, 4))  # three distinct paragraphs
        path.write_text(_page(paras, lang), encoding="utf-8")
        doc = load(str(path))
        assert text in doc.markdown, lang
        assert "Link 3" not in doc.markdown, lang
        assert doc.quality.word_count >= 40, lang  # not "very little text"
        assert doc.quality.language == lang


def test_style_inside_an_inline_element_is_not_text(tmp_path: Path) -> None:
    css = ".mw-parser-output cite.citation{font-style:inherit}"
    refs = "".join(
        f"<li><span class='ref'><style>{css}</style>Source number {i}, a book.</span></li>"
        for i in range(30)
    )
    page = f"<html><body><p>{ZH}</p><ol>{refs}</ol></body></html>"
    path = tmp_path / "refs.html"
    path.write_text(page, encoding="utf-8")
    assert "font-style" not in load(str(path)).markdown
