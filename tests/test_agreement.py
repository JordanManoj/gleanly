"""Cross-source agreement on numeric and date facts (search/agreement.py)."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from gleanly import Client, load
from gleanly.models import Document
from gleanly.search import search_with
from gleanly.search.agreement import check_agreement

PAGE = """<html><head><title>{title}</title></head><body><article><h1>{title}</h1>
{paras}</article></body></html>"""


def _doc(tmp_path: Path, name: str, *paras: str) -> Document:
    path = tmp_path / f"{name}.html"
    body = "".join(f"<p>{p}</p>" for p in paras)
    path.write_text(PAGE.format(title=name, paras=body), encoding="utf-8")
    return load(str(path))


A = (
    "The Eiffel Tower was completed in 1889 for the World's Fair held in Paris that year.",
    "The Eiffel Tower is 330 metres tall including its antennas, according to the operator.",
    "Ticket prices for the tower rise every summer, and the queues can be very long indeed.",
)
B = (
    "The Eiffel Tower was completed in 1887 for the World's Fair, according to this guide.",
    "Including the antennas, the Eiffel Tower is 330 metres tall, the operator says today.",
    "The city of Paris had 2.1 million inhabitants at the last census of its population.",
)


def test_conflicting_and_corroborated_facts(tmp_path: Path) -> None:
    a, b = _doc(tmp_path, "a", *A), _doc(tmp_path, "b", *B)
    report = check_agreement("Eiffel Tower", [("https://a.example", a), ("https://b.example", b)])

    years = [g for g in report.conflicts if g.kind == "year"]
    assert len(years) == 1
    values = {v.value for v in years[0].values}
    assert values == {"1889", "1887"}
    assert "completed" in years[0].topic
    src = years[0].values[0].sources[0]
    assert src.url in ("https://a.example", "https://b.example")
    assert "completed" in src.quote
    doc = a if src.url == "https://a.example" else b
    assert doc.markdown[src.char_start : src.char_end] == src.quote  # exact provenance

    heights = [g for g in report.corroborated if g.kind.startswith("unit:")]
    assert len(heights) == 1
    assert len(heights[0].values) == 1
    assert len(heights[0].values[0].sources) == 2


def test_unrelated_numbers_are_not_paired(tmp_path: Path) -> None:
    a = _doc(tmp_path, "a", "The Eiffel Tower has 1665 steps from the ground to the very top.")
    b = _doc(tmp_path, "b", "The Eiffel Tower welcomed 6 million visitors in the year 2023.")
    report = check_agreement("Eiffel Tower", [("https://a.example", a), ("https://b.example", b)])
    assert report.conflicts == []
    assert report.corroborated == []


def test_one_source_cannot_agree_with_itself(tmp_path: Path) -> None:
    a = _doc(tmp_path, "a", *A, "Again: the Eiffel Tower was completed in 1889, for the fair.")
    report = check_agreement("Eiffel Tower", [("https://a.example", a)])
    assert report.corroborated == []
    assert report.conflicts == []


def test_search_attaches_agreement(mock_http: respx.MockRouter) -> None:
    wiki = "https://en.wikipedia.org"
    mock_http.get(url__startswith=f"{wiki}/w/api.php").mock(
        return_value=httpx.Response(
            200, json={"query": {"search": [{"title": "Tower A"}, {"title": "Tower B"}]}}
        )
    )
    for path in ("/robots.txt", "/.well-known/tdmrep.json", "/ai.txt"):
        mock_http.get(f"{wiki}{path}").mock(return_value=httpx.Response(404))
    for title, paras in (("Tower_A", A), ("Tower_B", B)):
        html = PAGE.format(title=title, paras="".join(f"<p>{p}</p>" for p in paras))
        mock_http.get(f"{wiki}/wiki/{title}").mock(
            return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
        )

    async def run() -> None:
        async with Client(min_delay=0, browser="never") as c:
            resp = await search_with(c, "Eiffel Tower", backends=["wikipedia"])
        assert resp.agreement is not None
        assert any(g.kind == "year" for g in resp.agreement.conflicts)

    import asyncio

    asyncio.run(run())
