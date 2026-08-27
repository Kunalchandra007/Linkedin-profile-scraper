"""Validation and canonicalization of LinkedIn profile URLs.

Used both to validate incoming API requests and to build a stable cache key,
so the same profile requested via slightly different URLs hits one cache row.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

_LINKEDIN_HOST_RE = re.compile(r"(^|\.)linkedin\.com$", re.IGNORECASE)
_PROFILE_PATH_RE = re.compile(r"^/in/[^/]+$", re.IGNORECASE)


class InvalidLinkedInURL(ValueError):
    """Raised when a string is not a valid LinkedIn /in/<slug> profile URL."""


def normalize_linkedin_url(raw: str) -> str:
    """Validate and canonicalize a LinkedIn profile URL.

    Accepts inputs such as::

        https://www.linkedin.com/in/jane-doe/
        http://linkedin.com/in/jane-doe?originalSubdomain=uk
        linkedin.com/in/jane-doe

    Returns the canonical form ``https://www.linkedin.com/in/jane-doe``.
    Raises :class:`InvalidLinkedInURL` for anything else (company pages,
    feed URLs, non-LinkedIn hosts, etc.).
    """
    if not raw or not isinstance(raw, str):
        raise InvalidLinkedInURL("URL must be a non-empty string")

    candidate = raw.strip()
    if "://" not in candidate:
        candidate = "https://" + candidate

    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if not _LINKEDIN_HOST_RE.search(host):
        raise InvalidLinkedInURL(f"Not a linkedin.com URL: {raw!r}")

    path = parsed.path.rstrip("/")
    if not _PROFILE_PATH_RE.match(path):
        raise InvalidLinkedInURL(
            f"Not a LinkedIn profile URL (expected /in/<slug>): {raw!r}"
        )

    # Canonical: force https + www host, drop query/fragment/params.
    return urlunparse(("https", "www.linkedin.com", path, "", "", ""))


def profile_slug(url: str) -> str:
    """Return the ``<slug>`` from a normalized ``/in/<slug>`` URL."""
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1]
