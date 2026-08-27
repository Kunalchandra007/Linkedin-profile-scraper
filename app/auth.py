"""API-key authentication via the `X-API-Key` header.

A single static key from the environment — enough to keep the demo from being
wide open. Uses a constant-time comparison to avoid timing side channels.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected = settings.api_key
    if not expected or x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
            headers={"WWW-Authenticate": "API-Key"},
        )
