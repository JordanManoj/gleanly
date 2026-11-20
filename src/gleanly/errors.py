from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gleanly.models import FetchTrace


class AcquisitionError(Exception):
    """Base class for all errors raised by this library."""


class FetchError(AcquisitionError):
    """The source could not be fetched. ``trace`` explains every step that was tried."""

    def __init__(self, message: str, *, url: str | None = None, trace: FetchTrace | None = None):
        super().__init__(message)
        self.url = url
        self.trace = trace


class RobotsDisallowed(FetchError):
    """robots.txt does not allow this library to fetch the URL."""


class UnsupportedSourceError(AcquisitionError):
    """The source type is not supported (yet)."""


class BrowserUnavailable(AcquisitionError):
    """Playwright (the [browser] extra) is not installed or cannot start."""
