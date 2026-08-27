"""Shared test configuration.

The environment is configured *before* any app module is imported, so the whole
suite runs against a throwaway SQLite DB and the deterministic `fixture` provider —
no credentials, no network, no live LinkedIn.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# --- Configure environment BEFORE importing app modules -------------------
_TMP = Path(tempfile.mkdtemp(prefix="lpapi-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["API_KEY"] = "test-key"
os.environ["PROVIDER"] = "fixture"
os.environ["FIXTURE_DIR"] = str(Path(__file__).parent / "fixtures" / "profiles")
os.environ["CACHE_TTL_SECONDS"] = "3600"
os.environ["RUN_INLINE_WORKER"] = "true"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["FETCH_MIN_DELAY_SECONDS"] = "0.02"
os.environ["FETCH_MAX_DELAY_SECONDS"] = "0.05"

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

HTML_DIR = Path(__file__).parent / "fixtures" / "html"
API_KEY = "test-key"
AUTH = {"X-API-Key": API_KEY}


@pytest.fixture
async def clean_db():
    """Fresh tables + drained queue before a test (the temp DB file is shared)."""
    import aiosqlite

    from app import db
    from app.jobs import queue

    queue.clear()
    await db.init_db()
    async with aiosqlite.connect(get_settings().sqlite_path) as d:
        await d.execute("DELETE FROM profiles")
        await d.execute("DELETE FROM jobs")
        await d.commit()
    yield


@pytest.fixture
async def client(clean_db):
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.fixture
def full_html() -> str:
    return (HTML_DIR / "profile_full.html").read_text(encoding="utf-8")


@pytest.fixture
def minimal_html() -> str:
    return (HTML_DIR / "profile_minimal.html").read_text(encoding="utf-8")
