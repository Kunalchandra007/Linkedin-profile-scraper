"""MANUAL live smoke test against real LinkedIn — NOT for CI.

    python -m scripts.smoke_live https://www.linkedin.com/in/<slug>

Requires: the scraper extra installed, a saved session (scripts/login.py), and
you understand this performs a real, ToS-violating request. Run deliberately, on a
throwaway account only. Prints the scraped profile JSON.
"""

from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.logging_config import configure_logging, get_logger
from app.providers.linkedin import LinkedInProfileProvider
from app.urls import InvalidLinkedInURL, normalize_linkedin_url

logger = get_logger("smoke")


async def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m scripts.smoke_live <linkedin-profile-url>")
        return 2
    try:
        url = normalize_linkedin_url(sys.argv[1])
    except InvalidLinkedInURL as exc:
        print(f"error: {exc}")
        return 2

    settings = get_settings()
    configure_logging(settings.log_level)

    provider = LinkedInProfileProvider(settings)
    health = await provider.healthcheck()
    print(f"[health] {health.model_dump()}")
    if not health.ok:
        return 1

    result = await provider.fetch(url)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
