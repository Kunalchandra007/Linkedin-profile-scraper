"""Cache tests — the pure TTL check plus a store/lookup round-trip on SQLite."""

from datetime import UTC, datetime, timedelta

from app import cache
from app.schemas import Profile, ProfileResult
from app.urls import normalize_linkedin_url

URL = normalize_linkedin_url("https://www.linkedin.com/in/cache-test")
NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_is_fresh_within_ttl():
    assert cache.is_fresh(NOW - timedelta(seconds=10), 3600, now=NOW) is True


def test_is_fresh_beyond_ttl():
    assert cache.is_fresh(NOW - timedelta(seconds=7200), 3600, now=NOW) is False


def test_is_fresh_treats_naive_as_utc():
    naive = datetime(2024, 1, 1, 11, 59, 50)  # ~10s before NOW, no tzinfo
    assert cache.is_fresh(naive, 3600, now=NOW) is True


async def test_store_and_lookup_roundtrip(clean_db):
    result = ProfileResult(
        url=URL, source="mock", scraped_at=datetime.now(UTC), profile=Profile(name="Cache Test")
    )
    await cache.store(result)
    got = await cache.lookup(URL)
    assert got is not None
    assert got.profile.name == "Cache Test"
    assert got.url == URL


async def test_lookup_returns_none_when_stale(clean_db):
    old = datetime.now(UTC) - timedelta(days=999)
    await cache.store(ProfileResult(url=URL, source="mock", scraped_at=old, profile=Profile(name="Old")))
    # TTL is 3600s (conftest), so a 999-day-old row is stale.
    assert await cache.lookup(URL) is None


async def test_lookup_absent_returns_none(clean_db):
    assert await cache.lookup(normalize_linkedin_url("https://www.linkedin.com/in/never-stored")) is None
