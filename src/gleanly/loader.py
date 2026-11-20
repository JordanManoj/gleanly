from __future__ import annotations

import asyncio
from typing import Any

from gleanly.client import Client, Source
from gleanly.config import LoadOptions
from gleanly.models import Document


async def aload(source: Source, options: LoadOptions | None = None, **overrides: Any) -> Document:
    """Load a URL or local file into a :class:`Document` (async).

    For many sources, reuse one :class:`Client` so robots.txt caching and per-host
    rate limiting are shared.
    """
    async with Client(options, **overrides) as client:
        return await client.aload(source)


def load(source: Source, options: LoadOptions | None = None, **overrides: Any) -> Document:
    """Load a URL or local file into a :class:`Document`.

    Keyword overrides map to :class:`LoadOptions`, e.g. ``load(url, browser="never")``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(aload(source, options, **overrides))
    raise RuntimeError(
        "load() was called from a running event loop (e.g. Jupyter or async code); "
        "use `await aload(...)` instead."
    )
