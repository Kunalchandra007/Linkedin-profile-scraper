"""FixtureProfileProvider — serves canned profiles from JSON on disk.

Used by the test suite (and available via PROVIDER=fixture) so integration tests
have stable, realistic data without touching the network. Fixtures live in
`tests/fixtures/profiles/<slug>.json` and can be (re)generated with
`python -m scripts.make_fixtures`.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from app.providers.base import ProfileNotFoundError
from app.schemas import ProfileResult, ProviderHealth
from app.urls import profile_slug

DEFAULT_FIXTURE_DIR = "tests/fixtures/profiles"


class FixtureProfileProvider:
    name = "fixture"

    def __init__(self, fixture_dir: str | None = None) -> None:
        self._dir = Path(fixture_dir or os.environ.get("FIXTURE_DIR", DEFAULT_FIXTURE_DIR))

    def _path_for(self, slug: str) -> Path:
        return self._dir / f"{slug}.json"

    async def fetch(self, url: str) -> ProfileResult:
        slug = profile_slug(url)
        path = self._path_for(slug)
        if not path.is_file():
            raise ProfileNotFoundError(f"No fixture for slug {slug!r} in {self._dir}")

        raw = json.loads(path.read_text(encoding="utf-8"))
        result = ProfileResult.model_validate(raw)
        # Re-stamp identity fields so the fixture is portable across URLs/time.
        return result.model_copy(
            update={
                "url": url,
                "source": self.name,
                "scraped_at": datetime.now(UTC),
            }
        )

    async def healthcheck(self) -> ProviderHealth:
        available = self._dir.is_dir()
        n = len(list(self._dir.glob("*.json"))) if available else 0
        return ProviderHealth(
            provider=self.name,
            ok=available,
            detail=f"{n} fixture(s) in {self._dir}" if available else f"missing dir {self._dir}",
        )
