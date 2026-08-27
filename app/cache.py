"""TTL cache layer over the `profiles` table.

`is_fresh` is a pure function (unit-tested directly). `lookup` returns a cached
result only if it is within the configured TTL, so stale rows transparently
trigger a re-scrape.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db
from app.config import get_settings
from app.schemas import ProfileResult


def is_fresh(scraped_at: datetime, ttl_seconds: int, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if scraped_at.tzinfo is None:
        scraped_at = scraped_at.replace(tzinfo=timezone.utc)
    return (now - scraped_at) <= timedelta(seconds=ttl_seconds)


async def lookup(url: str) -> ProfileResult | None:
    """Return a fresh cached result for `url`, or None if absent/stale."""
    cached = await db.get_cached_profile(url)
    if cached is None:
        return None
    if is_fresh(cached.scraped_at, get_settings().cache_ttl_seconds):
        return cached
    return None


async def store(result: ProfileResult) -> None:
    await db.upsert_profile(result)
