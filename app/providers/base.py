"""Provider abstraction.

A `ProfileProvider` turns a canonical LinkedIn URL into a `ProfileResult`.
Everything above this layer (API, queue, cache, persistence) is provider-agnostic,
which is what lets the default `mock` provider power a fully testable, CI-safe app
while the real `linkedin` scraper stays an optional, opt-in adapter.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas import ProfileResult, ProviderHealth


class ProviderError(Exception):
    """Base class for provider failures. `retryable` tells the job runner
    whether a backoff-retry could plausibly succeed."""

    retryable: bool = False

    def __init__(self, message: str, *, retryable: bool | None = None) -> None:
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable


class ProfileNotFoundError(ProviderError):
    """The profile URL does not resolve to a profile (404 / removed)."""

    retryable = False


class ProfilePrivateError(ProviderError):
    """The profile exists but is private/restricted to the viewer."""

    retryable = False


class RateLimitedError(ProviderError):
    """The remote host is rate-limiting or showing a checkpoint/captcha."""

    retryable = True


class SessionExpiredError(ProviderError):
    """The authenticated session is no longer valid — needs a human re-login,
    so it is deliberately *not* retryable."""

    retryable = False


class TransientProviderError(ProviderError):
    """A transient error (timeout, navigation blip) worth retrying."""

    retryable = True


@runtime_checkable
class ProfileProvider(Protocol):
    name: str

    async def fetch(self, url: str) -> ProfileResult:
        """Return a populated `ProfileResult` for a canonical profile URL.

        May return *partial* data with `warnings` for degraded cases (e.g. a
        connection wall hiding some sections). Raises a `ProviderError`
        subclass for hard failures (not found, private, session dead, rate limit).
        """
        ...

    async def healthcheck(self) -> ProviderHealth:
        """Cheap readiness probe — must not perform an expensive scrape."""
        ...
