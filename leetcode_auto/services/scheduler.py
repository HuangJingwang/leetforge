"""Asyncio-based periodic task scheduler, replacing system-level daemon."""

from __future__ import annotations

import asyncio
from typing import Optional

_scheduler_task: Optional[asyncio.Task] = None


async def _sync_job():
    """Run sync in thread pool to avoid blocking event loop.

    Uses quiet=True to suppress desktop notifications for scheduled syncs.
    """
    from ..sync import sync
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: sync(interactive=False, quiet=True))


async def _run_scheduler(interval_minutes: int = 60):
    """Periodic sync loop."""
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            await _sync_job()
            print(f"Scheduled sync completed successfully")
        except Exception as e:
            print(f"Scheduled sync failed: {e}")


def start_scheduler(interval_minutes: int = 60):
    """Start the periodic scheduler as a background task."""
    global _scheduler_task
    try:
        loop = asyncio.get_running_loop()
        _scheduler_task = loop.create_task(_run_scheduler(interval_minutes))
        print(f"Scheduler started: sync every {interval_minutes} minutes")
    except RuntimeError:
        print("No running event loop, scheduler not started")


def stop_scheduler():
    """Cancel the scheduler task."""
    global _scheduler_task
    if _scheduler_task:
        _scheduler_task.cancel()
        _scheduler_task = None
