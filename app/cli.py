"""CLI: fetch a single profile and print JSON to stdout.

    python -m app.cli https://www.linkedin.com/in/some-slug
    python -m app.cli https://www.linkedin.com/in/some-slug --provider fixture

Uses the configured provider (default: mock), so it works with no credentials.
This is the direct-scrape entry point referenced in the project brief; it bypasses
the API/queue and calls a provider directly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import get_settings
from app.logging_config import configure_logging
from app.providers import get_provider
from app.urls import InvalidLinkedInURL, normalize_linkedin_url


async def _run(url: str, provider_name: str | None) -> None:
    settings = get_settings()
    if provider_name:
        settings = settings.model_copy(update={"provider": provider_name})
    provider = get_provider(settings)
    result = await provider.fetch(url)
    print(result.model_dump_json(indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch a LinkedIn profile as JSON.")
    parser.add_argument("url", help="LinkedIn profile URL (linkedin.com/in/<slug>)")
    parser.add_argument(
        "--provider",
        choices=["mock", "fixture", "linkedin"],
        default=None,
        help="Override the configured provider for this run.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress structured logs.")
    args = parser.parse_args(argv)

    configure_logging("WARNING" if args.quiet else get_settings().log_level)

    try:
        url = normalize_linkedin_url(args.url)
    except InvalidLinkedInURL as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    asyncio.run(_run(url, args.provider))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
