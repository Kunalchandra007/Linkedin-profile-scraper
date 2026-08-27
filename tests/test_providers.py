"""Provider tests — mock (deterministic synthetic) and fixture (canned JSON)."""

import pytest

from app.providers.base import ProfileNotFoundError
from app.providers.fixture import FixtureProfileProvider
from app.providers.mock import MockProfileProvider
from app.urls import normalize_linkedin_url

ADA = normalize_linkedin_url("https://www.linkedin.com/in/ada-lovelace")


async def test_mock_is_deterministic():
    prov = MockProfileProvider(latency_seconds=0.0)
    r1 = await prov.fetch(ADA)
    r2 = await prov.fetch(ADA)
    assert r1.profile.name == r2.profile.name
    assert r1.model_dump()["profile"] == r2.model_dump()["profile"]


async def test_mock_produces_full_shape():
    prov = MockProfileProvider(latency_seconds=0.0)
    r = await prov.fetch(ADA)
    prof = r.profile
    assert r.source == "mock"
    assert prof.name and prof.headline and prof.location and prof.about
    assert prof.experience and prof.education and prof.skills and prof.languages
    assert r.warnings  # flags that the data is synthetic


async def test_fixture_hit():
    prov = FixtureProfileProvider()  # FIXTURE_DIR from env (conftest)
    r = await prov.fetch(ADA)
    assert r.profile.name == "Ada Lovelace"
    assert r.source == "fixture"
    assert r.profile.skills[0].name == "Mathematics"


async def test_fixture_miss_raises_not_found():
    prov = FixtureProfileProvider()
    with pytest.raises(ProfileNotFoundError):
        await prov.fetch(normalize_linkedin_url("https://www.linkedin.com/in/nobody-here-xyz"))
