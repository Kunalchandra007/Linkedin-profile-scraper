"""Async SQLite persistence: the `profiles` cache and the `jobs` table.

`profiles` is the TTL cache keyed by canonical URL; `jobs` tracks the async
request lifecycle (queued -> running -> done|error). Connections are opened per
operation (simple and safe for a demo) with WAL enabled for read/write overlap.

Only SQLite is implemented here. The layer is small and self-contained, so
swapping in Postgres (asyncpg) later is localized to this file — noted as a
"next step" in the README.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from app.config import get_settings
from app.schemas import JobResponse, JobStatus, ProfileResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    url        TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    data_json  TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'done'
);
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    result_json TEXT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _db_path() -> str:
    settings = get_settings()
    if not settings.is_sqlite:
        raise NotImplementedError(
            "Only sqlite:// DATABASE_URLs are implemented in this demo. "
            "See db.py — adding Postgres (asyncpg) is localized to this module."
        )
    return settings.sqlite_path


def _connect() -> aiosqlite.Connection:
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return aiosqlite.connect(path)


async def init_db() -> None:
    async with _connect() as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.executescript(_SCHEMA)
        await db.commit()


# ─────────────────────────────── profiles cache ─────────────────────────────


async def get_cached_profile(url: str) -> ProfileResult | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT data_json FROM profiles WHERE url = ?", (url,)) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return ProfileResult.model_validate_json(row["data_json"])


async def upsert_profile(result: ProfileResult) -> None:
    async with _connect() as db:
        await db.execute(
            """
            INSERT INTO profiles (url, source, scraped_at, data_json, status)
            VALUES (?, ?, ?, ?, 'done')
            ON CONFLICT(url) DO UPDATE SET
                source=excluded.source,
                scraped_at=excluded.scraped_at,
                data_json=excluded.data_json,
                status='done'
            """,
            (result.url, result.source, result.scraped_at.isoformat(), result.model_dump_json()),
        )
        await db.commit()


# ─────────────────────────────────── jobs ───────────────────────────────────


async def create_job(
    url: str,
    status: JobStatus,
    *,
    result: ProfileResult | None = None,
    error: str | None = None,
) -> str:
    job_id = uuid.uuid4().hex
    now = _now_iso()
    async with _connect() as db:
        await db.execute(
            """
            INSERT INTO jobs (id, url, status, created_at, updated_at, result_json, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                url,
                status.value,
                now,
                now,
                result.model_dump_json() if result else None,
                error,
            ),
        )
        await db.commit()
    return job_id


async def set_job_status(
    job_id: str,
    status: JobStatus,
    *,
    result: ProfileResult | None = None,
    error: str | None = None,
) -> None:
    async with _connect() as db:
        await db.execute(
            """
            UPDATE jobs
               SET status = ?, updated_at = ?,
                   result_json = COALESCE(?, result_json),
                   error = ?
             WHERE id = ?
            """,
            (
                status.value,
                _now_iso(),
                result.model_dump_json() if result else None,
                error,
                job_id,
            ),
        )
        await db.commit()


async def get_job(job_id: str) -> JobResponse | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    data = ProfileResult.model_validate_json(row["result_json"]) if row["result_json"] else None
    return JobResponse(
        job_id=row["id"],
        status=JobStatus(row["status"]),
        url=row["url"],
        data=data,
        error=row["error"],
    )


async def claim_next_queued() -> str | None:
    """Atomically claim the oldest queued job for a standalone worker.

    The conditional UPDATE (``AND status='queued'``) makes the claim safe even if
    several workers race for the same row.
    """
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        job_id = row["id"]
        updated = await db.execute(
            "UPDATE jobs SET status='running', updated_at=? WHERE id=? AND status='queued'",
            (_now_iso(), job_id),
        )
        await db.commit()
        return job_id if updated.rowcount == 1 else None
