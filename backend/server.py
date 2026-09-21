"""TitanGym OS – FastAPI application bootstrap.

Composition:
  core       – config, db, security, time helpers, deps
  schemas    – request payload models
  services   – audit, notifications, payments, membership lifecycle
  scheduler  – APScheduler (daily lifecycle + notification retry)
  routers    – HTTP handlers grouped under /api/*
  seed       – idempotent demo data
"""
from __future__ import annotations

import logging
import os
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core import client, ensure_indexes, logger
from routers import api
from scheduler import shutdown_scheduler, start_scheduler
from seed import seed


class _RedactVerifyToken(logging.Filter):
    """Uvicorn access log includes the raw query string; redact hub.verify_token."""

    _pattern = re.compile(r"(hub\.verify_token=)[^&\s\"']+", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if record.args:
            record.args = tuple(self._pattern.sub(r"\1[REDACTED]", str(arg)) if isinstance(arg, str) else arg for arg in record.args)
        if isinstance(record.msg, str):
            record.msg = self._pattern.sub(r"\1[REDACTED]", record.msg)
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactVerifyToken())

app = FastAPI(title="TitanGym OS API", version="1.0.0")
app.include_router(api)


# ---------- CORS ----------
def _configure_cors() -> None:
    raw = os.environ.get("CORS_ORIGINS", "")
    configured = [origin.strip() for origin in raw.split(",") if origin.strip() and origin.strip() != "*"]
    frontend_origin = os.environ.get("FRONTEND_URL")
    if frontend_origin and frontend_origin not in configured:
        configured.append(frontend_origin)
    allow_origins = configured if configured else ["*"]
    allow_credentials = True  # Always allow credentials for cross-site cookies
    if configured:
        pattern = "|".join(re.escape(origin.rstrip("/")) for origin in configured)
        origin_regex: str | None = pattern
    else:
        origin_regex = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_origin_regex=origin_regex,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )


_configure_cors()


@app.on_event("startup")
async def _startup() -> None:
    await ensure_indexes()
    await seed()
    start_scheduler()
    logger.info("titangym.startup_complete")


@app.on_event("shutdown")
async def _shutdown() -> None:
    shutdown_scheduler()
    client.close()
    logger.info("titangym.shutdown_complete")
