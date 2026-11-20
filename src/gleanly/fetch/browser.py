"""Rung 3: render with a real browser (optional ``[browser]`` extra).

The browser identifies itself with the same honest User-Agent as plain HTTP.
No stealth plugins, fingerprint spoofing or CAPTCHA handling, by design.
"""

from __future__ import annotations

from dataclasses import dataclass

from gleanly.errors import BrowserUnavailable

INSTALL_HINT = (
    "Playwright is not installed. Install the extra with `pip install gleanly[browser]` "
    "and then run `playwright install chromium`."
)


@dataclass(frozen=True)
class RenderedPage:
    url: str
    html: str
    status_code: int | None


async def render_page(url: str, *, user_agent: str, timeout: float) -> RenderedPage:
    try:
        from playwright.async_api import (  # pyright: ignore[reportMissingImports]
            async_playwright,
        )
    except ImportError as exc:
        raise BrowserUnavailable(INSTALL_HINT) from exc

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch()
        except Exception as exc:  # binary missing, sandbox issues, ...
            raise BrowserUnavailable(
                f"Could not start Chromium ({exc}). Run `playwright install chromium`."
            ) from exc
        try:
            context = await browser.new_context(user_agent=user_agent)
            page = await context.new_page()
            response = await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            html = await page.content()
            return RenderedPage(
                url=page.url, html=html, status_code=response.status if response else None
            )
        finally:
            await browser.close()
