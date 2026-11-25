from __future__ import annotations

import importlib
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import respx

from gleanly import Client

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _glyphly_never_downloads() -> Iterator[None]:
    """Tests never download OCR models. glyphly reads with the models already on disk
    (CI fetches them before the tests); without its main models it is treated as absent,
    so "auto" falls back to Tesseract."""
    from gleanly.ocr import glyph

    with pytest.MonkeyPatch.context() as mp:
        try:
            glyphly = importlib.import_module("glyphly")
        except ImportError:
            yield
            return
        try:
            mp.setattr(glyph, "_reader", glyphly.Reader(download=False))
        except glyphly.ModelError:
            mp.setattr(glyph, "available", lambda: False)
        yield


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def mock_http() -> Iterator[respx.MockRouter]:
    """Every HTTP request must be mocked; unmatched requests fail the test."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    async with Client(min_delay=0, browser="never") as c:
        yield c
