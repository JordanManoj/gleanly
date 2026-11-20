from __future__ import annotations

import asyncio
import time


class DomainRateLimiter:
    """Enforce a minimum delay between requests to the same host.

    The effective delay is the larger of ``min_delay`` and the site's robots.txt
    ``Crawl-delay`` (when given).
    """

    def __init__(self, min_delay: float = 1.0) -> None:
        self.min_delay = min_delay
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, host: str, crawl_delay: float | None = None) -> float:
        """Sleep as needed; return the number of seconds waited."""
        delay = max(self.min_delay, crawl_delay or 0.0)
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            waited = 0.0
            last = self._last.get(host)
            if last is not None:
                waited = last + delay - time.monotonic()
                if waited > 0:
                    await asyncio.sleep(waited)
                else:
                    waited = 0.0
            self._last[host] = time.monotonic()
            return waited
