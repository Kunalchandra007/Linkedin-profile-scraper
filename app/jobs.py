"""Async job engine: an in-process queue, retry-with-backoff, and the worker
that turns a queued URL into a stored `ProfileResult`.

`submit()` implements the cache-then-enqueue policy used by the API. `process_job`
is shared by both the inline worker (started in the API lifespan) and the
standalone worker (`app/worker.py`), so the two paths can never diverge.

Failure policy (Phase 4): providers return *partial* results with `warnings` for
degraded pages; they raise `ProviderError` for hard failures. Retryable errors get
exponential backoff; non-retryable ones (not found, private, dead session) fail the
job fast with a clear message rather than throwing out of the worker.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from app import cache, db
from app.config import Settings, get_settings
from app.logging_config import get_logger, log_context
from app.providers import ProfileProvider
from app.providers.base import ProviderError
from app.schemas import EnqueueResponse, JobStatus, ProfileResult

logger = get_logger("jobs")


class JobQueue:
    """A thin wrapper around asyncio.Queue (kept behind an interface so the
    README's 'swap in Celery/RQ' next step is a localized change)."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[str] = asyncio.Queue()

    async def enqueue(self, job_id: str) -> None:
        await self._q.put(job_id)

    async def get(self) -> str:
        return await self._q.get()

    def task_done(self) -> None:
        self._q.task_done()

    def qsize(self) -> int:
        return self._q.qsize()

    def clear(self) -> None:
        """Reset the queue (used for test isolation).

        Recreating the underlying ``asyncio.Queue`` also drops any binding to a
        previous event loop — pytest-asyncio gives each test its own loop, and a
        queue first awaited on an earlier loop would otherwise raise
        "bound to a different event loop" in the next test.
        """
        self._q = asyncio.Queue()


queue = JobQueue()


async def submit(url: str) -> EnqueueResponse:
    """Cache-check then enqueue. On a fresh cache hit, returns a done job with
    data immediately; otherwise queues a scrape.

    The in-process queue is only fed when the inline worker is enabled. With a
    standalone worker (RUN_INLINE_WORKER=false) the job is picked up from the DB
    via ``claim_next_queued`` instead, so we skip the in-memory enqueue to avoid
    accumulating items nothing consumes.
    """
    cached = await cache.lookup(url)
    if cached is not None:
        job_id = await db.create_job(url, JobStatus.done, result=cached)
        logger.info("job.cache_hit", extra={"job_id": job_id, "target_url": url})
        return EnqueueResponse(
            job_id=job_id, status=JobStatus.done, url=url, cached=True, data=cached
        )

    job_id = await db.create_job(url, JobStatus.queued)
    if get_settings().run_inline_worker:
        await queue.enqueue(job_id)
    logger.info("job.enqueued", extra={"job_id": job_id, "target_url": url})
    return EnqueueResponse(job_id=job_id, status=JobStatus.queued, url=url, cached=False)


async def _with_retries(
    func: Callable[[], Awaitable[ProfileResult]],
    *,
    attempts: int,
    base_delay: float,
) -> ProfileResult:
    for attempt in range(1, attempts + 1):
        try:
            return await func()
        except ProviderError as exc:
            if not exc.retryable or attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "provider.retry",
                extra={"attempt": attempt, "delay_s": round(delay, 2), "error": str(exc)},
            )
            await asyncio.sleep(delay)
        except Exception as exc:  # unexpected: retry a couple times, then surface
            if attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "provider.retry_unexpected",
                extra={"attempt": attempt, "delay_s": round(delay, 2), "error": str(exc)},
            )
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


async def process_job(
    job_id: str,
    provider: ProfileProvider,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    job = await db.get_job(job_id)
    if job is None:
        logger.error("job.missing", extra={"job_id": job_id})
        return

    url = job.url
    with log_context(job_id=job_id, target_url=url, provider=provider.name):
        start = time.perf_counter()
        await db.set_job_status(job_id, JobStatus.running)
        try:
            result = await _with_retries(
                lambda: provider.fetch(url),
                attempts=3,
                base_delay=max(settings.fetch_min_delay_seconds, 0.2),
            )
        except ProviderError as exc:
            await db.set_job_status(
                job_id, JobStatus.error, error=f"{type(exc).__name__}: {exc}"
            )
            logger.warning(
                "job.failed",
                extra={
                    "outcome": "error",
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    "error_type": type(exc).__name__,
                },
            )
            return
        except Exception as exc:
            await db.set_job_status(job_id, JobStatus.error, error=f"Unexpected error: {exc}")
            logger.exception(
                "job.crashed",
                extra={
                    "outcome": "error",
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
            return

        await cache.store(result)
        await db.set_job_status(job_id, JobStatus.done, result=result)
        logger.info(
            "job.done",
            extra={
                "outcome": "done",
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                "warnings": len(result.warnings),
            },
        )


async def run_inline_worker(provider: ProfileProvider, settings: Settings | None = None) -> None:
    """Consume the in-process queue forever. Started as a background task by the
    API lifespan when RUN_INLINE_WORKER is true."""
    logger.info("worker.start", extra={"mode": "inline", "provider": provider.name})
    while True:
        job_id = await queue.get()
        try:
            await process_job(job_id, provider, settings)
        except Exception:
            logger.exception("worker.error", extra={"job_id": job_id})
        finally:
            queue.task_done()
