# syntax=docker/dockerfile:1
#
# Default image runs the CORE app (mock/fixture providers) — no browser engine,
# small and CI-safe. To build the optional LinkedIn-scraper variant (Playwright +
# Chromium), pass --build-arg INSTALL_SCRAPER=1. That variant is off-by-default and
# violates LinkedIn's ToS — see README "Known Limitations / ToS".

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build-time toggle for the optional scraper extra (Playwright/Chromium).
ARG INSTALL_SCRAPER=0

# Copy metadata first for better layer caching.
COPY pyproject.toml README.md ./
COPY app ./app

# Install the package. With INSTALL_SCRAPER=1 we also pull the `scraper` extra
# and provision Chromium + its OS dependencies.
RUN if [ "$INSTALL_SCRAPER" = "1" ]; then \
        pip install ".[scraper]" && \
        playwright install --with-deps chromium ; \
    else \
        pip install "." ; \
    fi

# Bundle fixtures so the `fixture` provider works out of the box.
COPY tests/fixtures ./tests/fixtures

# Persisted SQLite lives here (mount a volume in production).
RUN mkdir -p /app/data
ENV DATABASE_URL=sqlite:///./data/profiles.db \
    PROVIDER=mock \
    RUN_INLINE_WORKER=true \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# Non-root runtime user.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["linkedin-api"]
