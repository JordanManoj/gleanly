from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import respx

from gleanly import Client

FIXTURES = Path(__file__).parent / "fixtures"


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
