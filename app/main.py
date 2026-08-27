"""FastAPI application: routes, lifespan wiring, and request-context logging.

Endpoints:
    GET  /health                     - liveness + provider readiness (no auth)
    POST /api/v1/profile             - validate URL, cache-check, enqueue (auth)
    GET  /api/v1/profile/{job_id}    - poll job status / fetch result (auth)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status

from app import __version__, db, jobs
from app.auth import require_api_key
from app.config import get_settings
from app.logging_config import configure_logging, get_logger, log_context
from app.providers import get_provider
from app.schemas import (
    EnqueueResponse,
    HealthResponse,
    JobResponse,
    ProfileRequest,
)

logger = get_logger("api")

DESCRIPTION = (
    "Returns structured JSON for a LinkedIn profile URL via a pluggable provider "
    "(mock/fixture by default; an optional browser-automation scraper). "
    "NOTE: scraping LinkedIn violates its User Agreement — this is a portfolio/demo "
    "project. See the repository README's 'Known Limitations / ToS' section."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    await db.init_db()

    provider = get_provider(settings)
    app.state.provider = provider

    worker_task: asyncio.Task | None = None
    if settings.run_inline_worker:
        worker_task = asyncio.create_task(jobs.run_inline_worker(provider, settings))

    logger.info(
        "app.start",
        extra={"provider": provider.name, "inline_worker": settings.run_inline_worker},
    )
    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
        logger.info("app.stop")


app = FastAPI(
    title="LinkedIn Profile API",
    version=__version__,
    description=DESCRIPTION,
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    with log_context(request_id=rid, method=request.method, path=request.url.path):
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request.error",
                extra={"duration_ms": round((time.perf_counter() - start) * 1000, 1)},
            )
            raise
        response.headers["x-request-id"] = rid
        logger.info(
            "request.completed",
            extra={
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        return response


@app.get("/", include_in_schema=False)
async def root():
    return {
        "name": "LinkedIn Profile API",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health(request: Request) -> HealthResponse:
    provider = request.app.state.provider
    provider_health = await provider.healthcheck()
    return HealthResponse(version=__version__, provider=provider_health)


@app.post(
    "/api/v1/profile",
    response_model=EnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
    tags=["profile"],
)
async def create_profile_job(req: ProfileRequest, response: Response) -> EnqueueResponse:
    result = await jobs.submit(req.url)
    # Cache hit -> data returned immediately with 200 instead of 202.
    if result.cached:
        response.status_code = status.HTTP_200_OK
    return result


@app.get(
    "/api/v1/profile/{job_id}",
    response_model=JobResponse,
    dependencies=[Depends(require_api_key)],
    tags=["profile"],
)
async def get_profile_job(job_id: str) -> JobResponse:
    job = await db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown job_id")
    return job


def run() -> None:
    """Console-script entry point (`linkedin-api`).

    HOST/PORT are read from the environment so container platforms (Render, Fly,
    etc.) that inject a ``PORT`` work without code changes.
    """
    import os

    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        log_level=settings.log_level.lower(),
    )
