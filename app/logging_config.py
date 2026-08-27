"""Structured (JSON) logging with per-request context.

Every log line is a JSON object. Contextual fields (request id, target URL,
duration, outcome) are bound with :func:`log_context` and automatically appear
on every record emitted inside the block — so we never sprinkle PII-laden
strings through the code, and logs stay grep-/ingest-friendly.
"""

from __future__ import annotations

import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_log_context: ContextVar[dict[str, Any] | None] = ContextVar("_log_context", default=None)


@contextmanager
def log_context(**fields: Any):
    """Bind structured fields onto every log record emitted within the block."""
    merged = {**(_log_context.get() or {}), **fields}
    token = _log_context.set(merged)
    try:
        yield
    finally:
        _log_context.reset(token)


class JsonFormatter(logging.Formatter):
    _RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"taskName"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_log_context.get() or {})
        # Fields passed explicitly via logger.info(..., extra={...})
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and key not in payload and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
