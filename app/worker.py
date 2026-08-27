"""Standalone job worker.

For the demo the API runs an inline worker. To demonstrate horizontal scaling,
set RUN_INLINE_WORKER=false in .env and run this in a separate process:

    python -m app.worker

It claims queued jobs from the shared database (atomic claim in db.claim_next_queued)
and processes them with the same `process_job` the inline worker uses.
"""

from __future__ import annotations

import asyncio

from app import db
from app.config import get_settings
from app.jobs import process_job
from app.logging_config import configure_logging, get_logger
from app.providers import get_provider

logger = get_logger("worker")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await db.init_db()
    provider = get_provider(settings)
    logger.info("worker.start", extra={"mode": "standalone", "provider": provider.name})

    while True:
        job_id = await db.claim_next_queued()
        if job_id is None:
            await asyncio.sleep(1.0)
            continue
        await process_job(job_id, provider, settings)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
