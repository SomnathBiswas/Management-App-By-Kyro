"""APScheduler wiring for daily lifecycle and retry jobs (Asia/Kolkata)."""
from __future__ import annotations

import asyncio
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core import GYM_TZ, logger
from services import LifecycleService, NotificationService

_scheduler: Optional[AsyncIOScheduler] = None


async def _run_daily_lifecycle() -> None:
    try:
        counters = await LifecycleService.process_expiring_and_expired()
        logger.info("scheduler.lifecycle counters=%s", counters)
    except Exception:  # pragma: no cover
        logger.exception("scheduler.lifecycle_failed")


async def _run_retry_queue() -> None:
    try:
        processed = await NotificationService.process_retry_queue()
        if processed:
            logger.info("scheduler.retry processed=%s", processed)
    except Exception:  # pragma: no cover
        logger.exception("scheduler.retry_failed")


def start_scheduler() -> None:
    """Start the scheduler once per process."""
    global _scheduler
    if _scheduler is not None:
        return
    scheduler = AsyncIOScheduler(timezone=GYM_TZ)
    scheduler.add_job(
        _run_daily_lifecycle,
        CronTrigger(hour=0, minute=15, timezone=GYM_TZ),
        id="daily_lifecycle",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.add_job(
        _run_retry_queue,
        CronTrigger(minute="*/15", timezone=GYM_TZ),
        id="notification_retry",
        replace_existing=True,
        misfire_grace_time=600,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("scheduler.started tz=%s", GYM_TZ)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # pragma: no cover
            logger.exception("scheduler.shutdown_failed")
        _scheduler = None


async def trigger_lifecycle_now() -> dict:
    """Manual trigger used by admin endpoint and tests."""
    counters = await LifecycleService.process_expiring_and_expired()
    retries = await NotificationService.process_retry_queue()
    return {"lifecycle": counters, "retries_processed": retries}


def _ensure_event_loop_running() -> None:  # pragma: no cover - safety helper
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        raise RuntimeError("Scheduler requires a running event loop") from None
